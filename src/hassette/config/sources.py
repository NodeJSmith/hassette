"""Settings sources for one config build: what each source read, and file-relative paths.

`HassetteConfig.__init__` opens a `ConfigBuild` (see `hassette.config.build`) for the duration of
construction. The sources it creates read process env from the build's snapshot (never the live `os.environ`, which
``startup_tasks`` mutates), record the raw keys they read so the post-build checks see exactly the
config's inputs, and anchor relative paths: values from a file are relative to that file's
directory, values from the process env and init kwargs to the working directory.
"""

import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from logging import getLogger
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from mergedeep import merge
from pydantic import BaseModel
from pydantic_settings import BaseSettings, DotEnvSettingsSource, EnvSettingsSource
from pydantic_settings.sources import InitSettingsSource, TomlConfigSettingsSource
from pydantic_settings.sources.utils import parse_env_vars

from hassette.config.build import ENVIRONMENT_SOURCE, ConfigBuild, EnvKey, TomlTable
from hassette.config.classes import (
    AppManifest,
    is_path_annotation,
    local_overlay_paths,
    model_annotation,
    normalize_toml_file,
)
from hassette.config.locations import anchored, is_config_dir_env
from hassette.config.models import AppsConfig
from hassette.exceptions import ConfigError

LOGGER = getLogger(__name__)


class SnapshotEnvSettingsSource(EnvSettingsSource):
    """Env source that reads the build's environment snapshot and records the prefixed keys it saw."""

    def __init__(self, settings_cls: type[BaseSettings], build: ConfigBuild):
        # set before super().__init__, which calls _load_env_vars
        self.build = build
        super().__init__(settings_cls)

    # overrides a private pydantic-settings hook: the env mapping every env source reads.
    # test_unknown_keys.py's test_process_env_var fails if pydantic-settings stops calling it.
    def _load_env_vars(self) -> Mapping[str, str | None]:
        environ = self.build.environ
        record_keys(self.build, self, environ.items(), ENVIRONMENT_SOURCE)
        return parse_env_vars(environ, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)

    def __call__(self) -> dict[str, Any]:
        return anchor_paths(self.settings_cls, super().__call__(), self.build.cwd)


class FileDotEnvSettingsSource(DotEnvSettingsSource):
    """Dotenv source for one ``.env`` file: records its prefixed keys and anchors paths at its directory."""

    def __init__(self, settings_cls: type[BaseSettings], env_file: Path, build: ConfigBuild):
        # set before super().__init__, which calls _read_env_files
        self.path = env_file
        self.build = build
        super().__init__(settings_cls, env_file=env_file)

    # overrides a private pydantic-settings hook: the mapping read from the dotenv file(s).
    # test_unknown_keys.py's test_dotenv_var_any_case fails if pydantic-settings stops calling it.
    def _read_env_files(self) -> Mapping[str, str | None]:
        if not self.path.is_file():
            return {}
        try:
            raw = dict(dotenv_values(self.path, encoding=self.env_file_encoding or "utf8"))
        except (OSError, UnicodeDecodeError) as exc:  # python-dotenv skips malformed lines; it has no parse error
            raise config_file_error(self.path, exc) from exc
        # HASSETTE_CONFIG_DIR has no settings prefix but is a config_dir spelling: record it so a
        # .env that sets it is reported instead of silently ignored
        record_keys(self.build, self, raw.items(), str(self.path), also=is_config_dir_env)
        return parse_env_vars(raw, self.case_sensitive, self.env_ignore_empty, self.env_parse_none_str)

    def __call__(self) -> dict[str, Any]:
        return anchor_paths(self.settings_cls, super().__call__(), self.path.parent)


class HassetteTomlConfigSettingsSource(TomlConfigSettingsSource):
    """TOML source that hoists the ``[hassette]`` section and applies ``*.local.toml`` overlays.

    `toml_files` (absolute, lowest priority first) are read first: a later file replaces whole
    top-level keys of an earlier one. Each file's local overlay sibling (``hassette.toml`` ->
    ``hassette.local.toml``) is then deep-merged on top, so an overlay can override a single nested
    key without restating the rest of its table. Relative paths in each file are anchored at that
    file's directory before files combine. Each file's table is recorded on `build` for the
    post-build checks.
    """

    def __init__(self, settings_cls: type[BaseSettings], toml_files: Sequence[Path], build: ConfigBuild):
        self.toml_file_path = list(toml_files)
        base_files = self.toml_file_path

        # Normalize each file before combining, so a later file replaces an earlier one's logical
        # top-level table whether either file spells it `[apps]` or `[hassette.apps]`, and a later
        # field value wins whichever alias (`token` vs `ha_token`) either file uses.
        self.toml_data: dict[str, Any] = {}
        for path in base_files:
            if path.is_file():
                self.toml_data.update(self.read_table(settings_cls, path, build))

        for overlay in local_overlay_paths(base_files):
            if overlay.is_file():
                LOGGER.debug("Applying local TOML overlay %s", overlay)
                self.toml_data = dict(merge({}, self.toml_data, self.read_table(settings_cls, overlay, build)))

        # need to call InitSettingSource directly, as super() expects a file path
        # as the second argument
        InitSettingsSource.__init__(self, settings_cls, self.toml_data)

    def read_table(self, settings_cls: type[BaseSettings], path: Path, build: ConfigBuild) -> dict[str, Any]:
        try:
            raw = self._read_file(path)
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise config_file_error(path, exc) from exc
        table = normalize_toml_file(settings_cls, raw)
        build.toml_tables.append(TomlTable(path, table))
        return anchor_paths(settings_cls, table, path.parent)


def anchor_paths(model: type[BaseModel], data: dict[str, Any], base: Path) -> dict[str, Any]:
    """Return `data` with every relative value of a ``Path``-typed field made absolute against `base`.

    Walks `model`'s field tree, so new ``Path`` fields are covered without a list to update. App
    definitions are walked as `AppManifest` entries so their ``app_dir`` is anchored too. They come
    in two shapes under ``apps``::

        [hassette.apps.my_app]          # a table that isn't an AppsConfig field
        app_dir = "src/my_app"

        [hassette.apps.apps.my_app]     # an entry of the AppsConfig.apps mapping
        app_dir = "src/my_app"

    Values that aren't strings or paths, such as model instances passed as init kwargs, are left as
    they are.
    """
    out = dict(data)
    for key, value in data.items():
        info = model.model_fields.get(key)
        if info is None:
            if model is AppsConfig and isinstance(value, dict):  # [hassette.apps.my_app]
                out[key] = anchor_paths(AppManifest, value, base)
            continue
        if is_path_annotation(info.annotation):
            if value == "":  # unset, as an empty env var is (env_ignore_empty), not Path(".") in the working directory
                del out[key]
            else:
                out[key] = anchor(value, base)
        elif (sub := model_annotation(info.annotation)) is not None and isinstance(value, dict):
            out[key] = anchor_paths(sub, value, base)
        elif model is AppsConfig and key == "apps" and isinstance(value, dict):  # [hassette.apps.apps.my_app]
            out[key] = {k: anchor_paths(AppManifest, v, base) if isinstance(v, dict) else v for k, v in value.items()}
    return out


def config_file_error(path: Path, exc: Exception) -> ConfigError:
    """Return the `ConfigError` to raise (``from exc``) for a config file that can't be read or parsed."""
    return ConfigError(f"Can't load config file {path}: {exc}")


def anchor(value: Any, base: Path) -> Any:
    if not isinstance(value, str | Path):
        return value
    return anchored(value, base)


def record_keys(
    build: ConfigBuild,
    source: EnvSettingsSource,
    items: Iterable[tuple[str, str | None]],
    origin: str,
    also: Callable[[str], bool] = lambda _name: False,
) -> None:
    """Record each settings-prefixed name in `items` (and each name `also` accepts) as read from `origin`."""
    build.env_keys.extend(
        EnvKey(name, value, origin)
        for name, value in items
        if (name.lower().startswith(source.env_prefix) or also(name)) and not (source.env_ignore_empty and value == "")
    )
