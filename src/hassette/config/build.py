"""The inputs and records of one config build, visible to the settings sources and field defaults.

`HassetteConfig.__init__` opens a `ConfigBuild` for the duration of construction, so the settings
sources can read the build's environment snapshot and record what they read, and field defaults that
depend on the resolved locations (``apps.directory``, ``data_dir``) can see them.

The build travels in a `ContextVar` because neither reader can be handed it: pydantic-settings calls
the classmethod ``settings_customise_sources`` and each field's ``default_factory`` with no instance
and no extra arguments. Outside a build (a model constructed directly, such as ``AppsConfig()``) the
readers fall back to the live environment and the working directory.
"""

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hassette.config.locations import ConfigLocations, default_data_dir

ENVIRONMENT_SOURCE = "environment"
"""Source label for keys read from the process environment."""


@dataclass(frozen=True)
class EnvKey:
    """One ``HASSETTE__``-prefixed variable a source read."""

    name: str
    """The name as written (original case)."""

    value: str | None
    source: str
    """`ENVIRONMENT_SOURCE` or the ``.env`` file's path."""


@dataclass(frozen=True)
class TomlTable:
    """One TOML file's data after the ``[hassette]`` hoist and alias canonicalization."""

    path: Path
    data: dict[str, Any]


@dataclass
class ConfigBuild:
    """Inputs and records for constructing one config."""

    environ: Mapping[str, str] = field(repr=False)
    """Process environment snapshot that every build of this config reads (kept out of repr: it holds secrets)."""

    locations: ConfigLocations
    cwd: Path
    env_keys: list[EnvKey] = field(default_factory=list)
    toml_tables: list[TomlTable] = field(default_factory=list)


ACTIVE_BUILD: ContextVar[ConfigBuild | None] = ContextVar("hassette_active_config_build", default=None)


@contextmanager
def open_build(build: ConfigBuild) -> Iterator[ConfigBuild]:
    """Make `build` the one the settings sources of the config under construction read and record into."""
    token = ACTIVE_BUILD.set(build)
    try:
        yield build
    finally:
        ACTIVE_BUILD.reset(token)


def build_environ() -> Mapping[str, str]:
    """The environment snapshot of the build in progress, or the live environment outside of one."""
    build = ACTIVE_BUILD.get()
    return build.environ if build is not None else os.environ


def default_apps_dir() -> Path:
    """Default ``apps.directory``: ``<config home>/apps`` during a build, else ``./apps``."""
    build = ACTIVE_BUILD.get()
    return build.locations.default_apps_dir if build is not None else Path.cwd() / "apps"


def default_build_data_dir() -> Path:
    """Default ``data_dir``, reading ``HASSETTE_DATA_DIR`` from the build's environment snapshot."""
    return default_data_dir(build_environ())
