"""Checks that run on a config build's recorded inputs: unknown keys and ``config_dir`` set in a file.

Both checks read only what the settings sources recorded (see `hassette.config.sources`), so they
see exactly the inputs the config was built from: the process-env snapshot, the ``.env`` files
actually loaded, and the TOML files actually loaded.
"""

import difflib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, EnvSettingsSource

from hassette.config.build import ENVIRONMENT_SOURCE, ConfigBuild
from hassette.config.classes import AppManifest, is_mapping_annotation, model_annotation, str_aliases
from hassette.config.locations import ENV_NESTED_DELIMITER, SETTINGS_ENV_PREFIX, is_config_dir_env
from hassette.config.models import AppsConfig
from hassette.exceptions import ConfigError

CONFIG_REFERENCE_URL = "https://hassette.readthedocs.io/en/stable/pages/core-concepts/configuration/"
"""Docs-site configuration reference: ``site_url`` in ``mkdocs.yml``, the version, then the page's path under
``docs/`` (``pages/core-concepts/configuration/index.md``)."""


ERROR_SOURCE_ENVIRONMENT = "environment"
ERROR_SOURCE_FILE = "file"
"""``hassette run --check`` reports a config error's source as one of these; ``docker_start.sh`` matches them."""


class EnvironmentConfigError(ConfigError):
    """A `ConfigError` that at least one process-env variable contributes to.

    The process must be recreated with a fixed environment to clear it, which matters to a
    supervisor: ``hassette run --check`` reports it as ``CONFIG_ERROR_SOURCE=environment``. When
    files contribute too, that remedy still covers them: recreating the container also rereads its
    mounted files, while a plain restart would keep the bad environment.
    """


@dataclass(frozen=True)
class UnknownKey:
    """A key that matches no setting, with where it was found and the closest real setting name."""

    name: str
    source: str
    suggestion: str | None


def check_config_dir_not_in_files(build: ConfigBuild) -> None:
    """Raise `ConfigError` when ``config_dir`` is set in a ``.env`` or TOML file.

    Both files are found through ``config_dir``, so a value there can't change where they are found.
    """
    sources = [key.source for key in build.env_keys if key.source != ENVIRONMENT_SOURCE and is_config_dir_env(key.name)]
    sources += [str(table.path) for table in build.toml_tables if "config_dir" in table.data]
    if sources:
        raise ConfigError(
            f"`config_dir` can't be set in a config file (found in {', '.join(dict.fromkeys(sources))}): "
            "Hassette finds hassette.toml and .env through config_dir, so the value would be read too late "
            "to take effect. Set the HASSETTE__CONFIG_DIR environment variable or pass --config-dir instead."
        )


def check_unknown_keys(settings_cls: type[BaseSettings], build: ConfigBuild) -> None:
    """Raise `ConfigError` listing every recorded key that matches no setting."""
    unknown = find_unknown_keys(settings_cls, build)
    if any(key.source == ENVIRONMENT_SOURCE for key in unknown):
        raise EnvironmentConfigError(format_unknown_keys(unknown))
    if unknown:
        raise ConfigError(format_unknown_keys(unknown))


def config_error_from_validation(exc: ValidationError, build: ConfigBuild) -> ConfigError:
    """Wrap a construction `ValidationError`; `EnvironmentConfigError` when a process-env variable set a failing field.

    A field counts as env-set when a recorded process-env name spells its path or one of its parents
    (``HASSETTE__LOGGING`` or ``HASSETTE__LOGGING__LOG_LEVEL`` for ``logging.log_level``). List
    indices in the error location are skipped. A value set through an alias spelling
    (``HASSETTE__HA_TOKEN``) isn't matched and counts as a file error.
    """
    env_names = {key.name.lower() for key in build.env_keys if key.source == ENVIRONMENT_SOURCE}
    for error in exc.errors():
        path = [part for part in error["loc"] if isinstance(part, str)]
        for depth in range(1, len(path) + 1):
            if SETTINGS_ENV_PREFIX + ENV_NESTED_DELIMITER.join(path[:depth]).lower() in env_names:
                return EnvironmentConfigError(str(exc))
    return ConfigError(str(exc))


def find_unknown_keys(settings_cls: type[BaseSettings], build: ConfigBuild) -> list[UnknownKey]:
    """Return each recorded key that matches no setting, once, in the order the sources read them."""
    env_names = EnvNames.for_settings(settings_cls)
    # env names are keyed uppercased and TOML names are dotted, so the two never collide
    found: dict[str, UnknownKey] = {}

    for key in build.env_keys:
        if not env_names.is_known(key.name, key.value):
            found.setdefault(key.name.upper(), UnknownKey(key.name, key.source, env_names.suggest(key.name)))

    for table in build.toml_tables:
        for name in unknown_toml_keys(settings_cls, table.data):
            found[name] = UnknownKey(name, str(table.path), suggest_toml_name(settings_cls, name))

    return list(found.values())


def format_unknown_keys(unknown: list[UnknownKey]) -> str:
    lines = ["Unknown configuration keys (they match no Hassette setting):"]
    for key in unknown:
        line = f"  - {key.name} (from {key.source})"
        if key.suggestion:
            line += f": did you mean {key.suggestion}?"
        lines.append(line)
    if any(key.name.lower().startswith(SETTINGS_ENV_PREFIX) for key in unknown):
        lines.append(
            "The HASSETTE__ prefix is reserved for Hassette settings; "
            "an app's own environment variables need a different prefix."
        )
    lines.append(f"See the configuration reference: {CONFIG_REFERENCE_URL}")
    return "\n".join(lines)


class EnvNames:
    """The env names pydantic-settings maps to a setting, and the prefixes under which any name is accepted.

    The ``HASSETTE__APPS__<key>`` namespace is dynamic (app definitions), so `is_known` treats it apart.
    """

    def __init__(self, known: set[str], open_prefixes: set[str], apps_prefix: str, apps_fields: set[str]):
        self.known = known
        self.open_prefixes = open_prefixes
        self.apps_prefix = apps_prefix
        self.apps_fields = apps_fields

    @classmethod
    def for_settings(cls, settings_cls: type[BaseSettings]) -> "EnvNames":
        # pydantic-settings' own per-field env-name computation, so aliases and the prefix match it exactly
        source = EnvSettingsSource(settings_cls)
        known: set[str] = set()
        open_prefixes: set[str] = set()
        for field_name, info in settings_cls.model_fields.items():
            for _, env_name, _ in source._extract_field_info(info, field_name):  # pyright: ignore[reportPrivateUsage]
                collect_env_names(env_name.lower(), info, known, open_prefixes)
        apps_prefix = f"{source.env_prefix}apps{ENV_NESTED_DELIMITER}"
        return cls(known, open_prefixes, apps_prefix, {n.lower() for n in field_names(AppsConfig)})

    def is_known(self, name: str, value: str | None) -> bool:
        lowered = name.lower()
        if lowered in self.known or any(lowered.startswith(prefix) for prefix in self.open_prefixes):
            return True
        if not lowered.startswith(self.apps_prefix):
            return False
        segments = lowered[len(self.apps_prefix) :].split(ENV_NESTED_DELIMITER)
        if segments[0] in self.apps_fields:
            # a real AppsConfig field that isn't in `known`: a bad sub-key, e.g. HASSETTE__APPS__DIRECTORY__X
            return False
        # anything else under HASSETTE__APPS__ names an app: HASSETTE__APPS__<KEY>__FILENAME=...,
        # or HASSETTE__APPS__<KEY>='{"filename": ...}' (a scalar HASSETTE__APPS__<KEY>=x is a typo)
        return len(segments) > 1 or is_json_object(value)

    def suggest(self, name: str) -> str | None:
        matches = difflib.get_close_matches(name.lower(), sorted(self.known), n=1)
        return matches[0].upper() if matches else None


def collect_env_names(env_name: str, info: FieldInfo, known: set[str], open_prefixes: set[str]) -> None:
    """Add `env_name` and, for a nested model, each nested env name below it."""
    known.add(env_name)
    sub = model_annotation(info.annotation)
    if sub is None:
        if is_mapping_annotation(info.annotation):
            open_prefixes.add(env_name + ENV_NESTED_DELIMITER)
        return
    for sub_name, sub_info in sub.model_fields.items():
        for name in field_spellings(sub_name, sub_info):
            collect_env_names(f"{env_name}{ENV_NESTED_DELIMITER}{name.lower()}", sub_info, known, open_prefixes)


def unknown_toml_keys(model: type[BaseModel], data: dict[str, Any], prefix: str = "") -> Iterator[str]:
    """Yield the dotted name of each key in `data` that matches no field of `model`.

    Table-valued keys under ``apps`` that aren't ``AppsConfig`` fields are app definitions and are
    not checked.
    """
    names = {spelling: info for name, info in model.model_fields.items() for spelling in field_spellings(name, info)}
    for key, value in data.items():
        info = names.get(key)
        if info is None:
            if model is AppsConfig and isinstance(value, dict):
                continue
            yield f"{prefix}{key}"
            continue
        sub = model_annotation(info.annotation)
        if sub is not None and sub is not AppManifest and isinstance(value, dict):
            yield from unknown_toml_keys(sub, value, f"{prefix}{key}.")


def suggest_toml_name(model: type[BaseModel], dotted: str) -> str | None:
    """Return the setting in the same table whose name is closest to `dotted`'s last segment."""
    *parents, leaf = dotted.split(".")
    for parent in parents:
        model = model_annotation(model.model_fields[parent].annotation) or model
    matches = difflib.get_close_matches(leaf, sorted(model.model_fields), n=1)
    return ".".join([*parents, matches[0]]) if matches else None


def field_spellings(name: str, info: FieldInfo) -> list[str]:
    """The field name plus every string alias pydantic accepts for it."""
    return list(dict.fromkeys([name, *str_aliases(info)]))


def field_names(model: type[BaseModel]) -> Iterator[str]:
    for name, info in model.model_fields.items():
        yield from field_spellings(name, info)


def is_json_object(value: str | None) -> bool:
    if not value:
        return False
    try:
        return isinstance(json.loads(value), dict)
    except ValueError:
        return False
