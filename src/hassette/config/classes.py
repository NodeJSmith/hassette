from copy import deepcopy
from logging import getLogger
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import UnionType
from typing import Any, Union, get_args, get_origin
from warnings import warn

from mergedeep import merge
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings

from hassette.types.types import is_framework_key

LOCAL_OVERLAY_INFIX = ".local"

LOGGER = getLogger(__name__)


def local_overlay_paths(files: list[Path]) -> list[Path]:
    """Return the local overlay sibling path of each TOML file (``hassette.toml`` -> ``hassette.local.toml``).

    Paths are derived, not checked; callers filter to the overlays that exist.
    """
    return [p.with_name(f"{p.stem}{LOCAL_OVERLAY_INFIX}{p.suffix}") for p in files]


def model_annotation(annotation: Any) -> type[BaseModel] | None:
    """Return the pydantic model `annotation` names, or None."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    return None


def is_path_annotation(annotation: Any) -> bool:
    """True when `annotation` is ``Path`` or a union containing it (``Path | None``)."""
    if annotation is Path:
        return True
    return get_origin(annotation) in (Union, UnionType) and Path in get_args(annotation)


def is_mapping_annotation(annotation: Any) -> bool:
    """True when `annotation` is ``dict`` or a parameterized ``dict[...]``."""
    return getattr(annotation, "__origin__", annotation) is dict


def str_aliases(info: FieldInfo) -> tuple[str, ...]:
    """Return the string aliases pydantic validates `info`'s field by, in lookup order.

    A ``validation_alias`` replaces ``alias`` for validation, so only one of them counts.
    """
    alias = info.validation_alias or info.alias
    choices = alias.choices if isinstance(alias, AliasChoices) else (alias,)
    return tuple(c for c in choices if isinstance(c, str))


def alias_groups(model: type[BaseModel]) -> list[tuple[str, ...]]:
    """Return each multi-spelling field's string aliases in pydantic's lookup order; the first is canonical."""
    groups: list[tuple[str, ...]] = []
    for info in model.model_fields.values():
        names = str_aliases(info)
        if len(names) > 1:
            groups.append(names)
    return groups


def canonicalize_aliases(data: dict[str, Any], groups: list[tuple[str, ...]]) -> dict[str, Any]:
    """Rewrite alias keys to each group's canonical spelling; if several are present, the first in order wins."""
    out = dict(data)
    for group in groups:
        present = [k for k in group if k in out]
        if present and present != [group[0]]:
            value = out[present[0]]
            for key in present:
                del out[key]
            out[group[0]] = value
    return out


def canonicalize_table(settings_cls: type[BaseSettings], data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize a table's top-level field aliases and the keys of each app entry under ``apps``."""
    out = canonicalize_aliases(data, alias_groups(settings_cls))
    apps = out.get("apps")
    if isinstance(apps, dict):
        manifest_groups = alias_groups(AppManifest)
        out["apps"] = {
            k: canonicalize_aliases(v, manifest_groups) if isinstance(v, dict) else v for k, v in apps.items()
        }
    return out


def normalize_toml_file(settings_cls: type[BaseSettings], data: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize one TOML file's aliases, then merge its ``[hassette]`` section into its top level.

    Canonicalizing per file (before any layering) means a later file or overlay always overrides an
    earlier one regardless of which alias each spells. Within a file, ``[hassette]`` values win.
    """
    top_level = canonicalize_table(settings_cls, {k: v for k, v in data.items() if k != "hassette"})
    if "hassette" not in data:
        return top_level

    LOGGER.debug("Merging 'hassette' section from TOML config into top level")
    hassette_values = canonicalize_table(settings_cls, data["hassette"])

    # Diagnostic only: the merge below always lets [hassette] win.
    for key in set(top_level).intersection(hassette_values):
        if not (isinstance(top_level[key], dict) and isinstance(hassette_values[key], dict)):
            LOGGER.warning(
                "Key %r found in both top level and 'hassette' section of TOML config, "
                "the [hassette] value will be used",
                key,
            )

    return dict(merge({}, top_level, hassette_values))


class ExcludeExtrasMixin:
    """Mixin that excludes ``model_extra`` keys from serialization by default.

    Models using ``extra="allow"`` silently collect unrecognised fields in
    ``model_extra``.  This mixin overrides ``model_dump`` and
    ``model_dump_json`` so those extra keys are excluded unless the caller
    explicitly passes ``include``.  This prevents accidental exposure of
    sensitive values (e.g. tokens, secrets) during serialization.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    def get_extra_keys(self) -> set[str]:
        extras = getattr(self, "model_extra", None)
        return set(extras) if extras else set()

    @staticmethod
    def merge_exclude(exclude: Any | None, extra_keys: set[str]) -> Any:
        """Merge extra keys into an existing ``exclude`` value.

        Handles the three shapes Pydantic accepts for *exclude*:
        - ``None``  → return a new ``set`` of extra keys
        - ``dict``  → copy and mark each extra key as ``True`` (fully excluded)
        - ``set`` (or other iterable) → union with extra keys
        """
        if exclude is None:
            return set(extra_keys)
        if isinstance(exclude, dict):
            return {**exclude, **dict.fromkeys(extra_keys, True)}
        return set(exclude) | extra_keys

    def model_dump(self, *, exclude: Any | None = None, **kwargs: Any) -> dict[str, Any]:
        """Serialize declared fields only; extra fields are excluded for privacy."""
        extra_keys = self.get_extra_keys()
        # Skip auto-exclude when caller explicitly specifies `include` — respect their selection
        if extra_keys and kwargs.get("include") is None:
            exclude = self.merge_exclude(exclude, extra_keys)
        return super().model_dump(exclude=exclude, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]

    def model_dump_json(self, *, exclude: Any | None = None, **kwargs: Any) -> str:
        """Serialize declared fields only; extra fields are excluded for privacy."""
        extra_keys = self.get_extra_keys()
        if extra_keys and kwargs.get("include") is None:
            exclude = self.merge_exclude(exclude, extra_keys)
        return super().model_dump_json(exclude=exclude, **kwargs)  # pyright: ignore[reportAttributeAccessIssue]


class AppManifest(ExcludeExtrasMixin, BaseModel):
    """Manifest for a Hassette app."""

    model_config = ConfigDict(
        extra="allow", coerce_numbers_to_str=True, validate_assignment=True, use_attribute_docstrings=True
    )

    app_key: str = Field(default=...)
    """Reflects the key for this app in hassette.toml"""

    enabled: bool = Field(default=True)
    """Whether the app is enabled or not, will default to True if not set. Does not consider ``--app`` filter."""

    autostart: bool = Field(default=True)
    """Whether the app starts automatically when Hassette starts. Orthogonal to
    `enabled`: an enabled app with autostart=false is registered and startable on
    demand, but is not started at startup or by a live config reload."""

    filename: str = Field(default=..., examples=["my_app.py"], validation_alias=AliasChoices("filename", "file_name"))
    """Filename of the app, will be looked for in app_path"""

    class_name: str = Field(
        default=..., examples=["MyApp"], validation_alias=AliasChoices("class_name", "class", "module", "module_name")
    )
    """Class name of the app"""

    display_name: str = Field(default=..., examples=["My App"])
    """Display name of the app, will use class_name if not set"""

    app_dir: Path = Field(..., examples=["./apps"])
    """Path to the app directory: absolute, or relative to the config file that sets it"""

    app_config: dict[str, Any] | list[dict[str, Any]] = Field(
        default_factory=dict, validation_alias=AliasChoices("config", "app_config"), validate_default=True
    )
    """Instance configuration for the app"""

    auto_loaded: bool = Field(default=False)
    """Whether the app was auto-detected or manually configured"""

    full_path: Path
    """Fully resolved path to the app file"""

    cache_key: str = Field(default="")
    """Override the cache directory key. When empty (default), App.cache_key computes
    '{app_key}/{index}'. When set, this value is used as-is."""

    cache_shared: bool = Field(default=False)
    """Mark this app's resolved cache_key as intentionally shared with other apps. The
    cache_key collision warning is suppressed only when every app sharing the key sets this."""

    def __repr__(self) -> str:
        return (
            f"<AppManifest {self.display_name} ({self.class_name})"
            f" - enabled={self.enabled} autostart={self.autostart} file={self.filename}>"
        )

    @model_validator(mode="before")
    @classmethod
    def validate_app_manifest(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Validate the app configuration."""
        required_keys = ["filename", "class_name", "app_dir"]
        missing_keys = [key for key in required_keys if key not in values]
        if missing_keys:
            raise ValueError(f"App configuration is missing required keys: {', '.join(missing_keys)}")

        values["app_dir"] = app_dir = Path(values["app_dir"]).resolve()

        if not values.get("display_name"):
            values["display_name"] = values.get("class_name") if values.get("auto_loaded") else values.get("app_key")

        if app_dir.is_file():
            LOGGER.warning("App directory %s is a file, using the parent directory as app_dir", app_dir)
            values["filename"] = app_dir.name
            values["app_dir"] = app_dir.parent

        return values

    @field_validator("app_config", mode="before")
    @classmethod
    def validate_app_config(cls, v: Any, validation_info: ValidationInfo) -> Any:
        """Set instance name if not set in config."""
        if not v:
            return v

        if isinstance(v, dict):
            v = [v]

        class_name = validation_info.data.get("class_name", "UnknownApp")

        for idx, item in enumerate(v):
            if "instance_name" not in item or not item["instance_name"]:
                item["instance_name"] = f"{class_name}.{idx}"

        return v

    @field_validator("cache_key")
    @classmethod
    def validate_cache_key(cls, v: str) -> str:
        if not v:
            return v
        if is_framework_key(v):
            raise ValueError(f"cache_key {v!r} uses a framework-reserved prefix")
        if reason := unsafe_cache_path_reason(v):
            raise ValueError(f"cache_key {v!r} {reason}")
        return v

    def validate_model_extra(self) -> None:
        if not self.model_extra:
            return

        keys = list(self.model_extra.keys())
        msg = (
            f"{type(self).__name__} - {self.display_name} - Instance configuration values should be"
            " set under the `config` field:\n"
            f"  {keys}\n"
            "This will ensure proper validation and handling of custom configurations."
        )

        if not self.app_config:
            self.app_config = deepcopy(self.model_extra)
        elif isinstance(self.app_config, dict) and not set(self.app_config).intersection(set(keys)):
            self.app_config.update(deepcopy(self.model_extra))
        else:
            if isinstance(self.app_config, list):
                msg += "\nNote: Unable to merge extra fields into list-based config."
            elif isinstance(self.app_config, dict):
                msg += "\nNote: Unable to merge extra fields into existing config due to intersecting keys."

            msg += "\nExtra fields will be ignored. Please update your configuration."

        warn(msg, stacklevel=5)

    def model_post_init(self, context: Any) -> None:
        self.validate_model_extra()

        # if we don't have app_config then we don't have any apps with config
        # which means we have, at most, one app
        # so we can just set the default instance name
        if not self.app_config:
            self.app_config = [{"instance_name": f"{self.class_name}.0"}]


def unsafe_cache_path_reason(value: str) -> str | None:
    """Return why *value* can't be used as a cache path under ``data_dir``, or None if it is safe.

    This is the single definition of a safe cache path, shared by explicit ``cache_key`` values and
    by the app keys that default cache keys are derived from.
    """
    # Parse under both flavors so the verdict doesn't depend on the host OS: a value like "C:" or "\\x" is
    # an ordinary name on POSIX but drive- or root-anchored on Windows, where joining it discards data_dir.
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if not posix.parts:
        # "" and "." resolve to data_dir itself; an empty app key would also turn "{app_key}/{index}"
        # into the absolute "/{index}".
        return "must name a subdirectory of data_dir (not be empty or '.')"
    if posix.anchor or windows.anchor:
        return "must be a relative path"
    if ".." in posix.parts or ".." in windows.parts:
        return "must not contain parent-directory traversal"
    return None
