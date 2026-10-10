"""Where Hassette's config files, config home, and default data directory are.

`resolve_locations` is the single owner of these answers. The config loader, the file watcher,
`AppConfig`'s ``.env`` lookup, the unknown-key check and ``hassette run --check`` all read its
result instead of computing their own.
"""

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

import platformdirs

from hassette.utils import get_parsed_version

CONFIG_FILE_NAME = "hassette.toml"
ENV_FILE_NAME = ".env"
DOCKER_CONFIG_DIR = Path("/config")
DOCKER_DATA_DIR = Path("/data")

SETTINGS_ENV_PREFIX = "hassette__"
"""Prefix of every env var that sets a Hassette setting; reserved for settings."""

ENV_NESTED_DELIMITER = "__"
"""Separator between nested setting names in an env var (``HASSETTE__LOGGING__LOG_LEVEL``)."""

CONFIG_DIR_ENV_NAMES = ("hassette__config_dir", "hassette_config_dir")
"""Env names that set `config_dir` explicitly, in priority order (compared case-insensitively)."""

DATA_DIR_ENV_NAMES = ("hassette__data_dir", "hassette_data_dir")
"""Env names `default_data_dir` reads, in priority order (compared case-insensitively).

The env settings source also reads ``HASSETTE__DATA_DIR`` as the ``data_dir`` field; both give the
same value, and this lookup is what lets the field default see it before the sources run."""

VERSION = get_parsed_version()

FileList = str | PurePath | Sequence[str | PurePath]
"""One path or a list of paths; an empty list means no files."""


@dataclass(frozen=True)
class ConfigLocations:
    """The resolved config locations for one process."""

    config_dir: Path
    """Absolute config directory: the explicit setting, else ``/config`` if it exists, else platformdirs."""

    config_dir_explicit: bool
    """Whether `config_dir` came from ``--config-dir``, an env var, or an init kwarg."""

    cwd: Path
    """Resolved directory that relative location inputs, env and CLI paths anchor at."""

    config_home: Path
    """Absolute anchor for config-relative defaults (``<config home>/apps``).

    The explicit `config_dir`, else ``/config`` if it exists, else cwd."""

    toml_files: tuple[Path, ...]
    """Absolute TOML files to read, lowest priority first. Missing files are skipped when loading."""

    env_files: tuple[Path, ...]
    """Absolute ``.env`` files to read, lowest priority first. Missing files are skipped when loading."""

    toml_files_explicit: bool
    """Whether `toml_files` was named (``--config-file``, a pinned ``toml_file``) rather than searched."""

    env_files_explicit: bool
    """Whether `env_files` was named (``--env-file``, a pinned ``env_file``) rather than searched."""

    @property
    def default_apps_dir(self) -> Path:
        """Default for ``apps.directory`` when no source sets it."""
        return self.config_home / "apps"


def resolve_locations(
    environ: Mapping[str, str],
    *,
    config_dir: str | PurePath | None = None,
    config_file: FileList | None = None,
    env_file: FileList | None = None,
    cwd: Path | None = None,
) -> ConfigLocations:
    """Resolve the config locations from explicit inputs and the process environment.

    Args:
        environ: The process environment to read ``HASSETTE__CONFIG_DIR``/``HASSETTE_CONFIG_DIR`` from.
        config_dir: An explicit config directory (``--config-dir`` or a ``config_dir`` init kwarg).
            Beats the env vars.
        config_file: Replaces the TOML search list (``--config-file``). ``None`` searches.
        env_file: Replaces the ``.env`` search list (``--env-file``). ``None`` searches.
        cwd: Directory relative inputs resolve against. Defaults to the current working directory.

    With an explicit `config_dir`, only that directory is searched. Otherwise the search list is
    the default config dir, then cwd, then ``./config``; later files win. The config home is the
    explicit `config_dir`, else ``/config`` if it exists, else cwd.
    """
    cwd = (cwd or Path.cwd()).resolve()

    explicit = config_dir if config_dir is not None else env_lookup(environ, CONFIG_DIR_ENV_NAMES)
    if explicit is not None:
        resolved_dir = anchored(explicit, cwd)
        search_dirs = [resolved_dir]
        config_home = resolved_dir
    else:
        resolved_dir = default_config_dir()
        search_dirs = [resolved_dir, cwd, cwd / "config"]
        # default_config_dir() returns /config only when it exists, which marks Docker or the add-on,
        # where cwd is the image's own install
        config_home = resolved_dir if resolved_dir == DOCKER_CONFIG_DIR else cwd

    return ConfigLocations(
        config_dir=resolved_dir,
        config_dir_explicit=explicit is not None,
        cwd=cwd,
        config_home=config_home,
        toml_files=file_list(config_file, cwd) if config_file is not None else search(search_dirs, CONFIG_FILE_NAME),
        env_files=file_list(env_file, cwd) if env_file is not None else search(search_dirs, ENV_FILE_NAME),
        toml_files_explicit=config_file is not None,
        env_files_explicit=env_file is not None,
    )


def default_config_dir() -> Path:
    """Return ``/config`` when it exists (Docker and the add-on), else the platformdirs user config path."""
    if DOCKER_CONFIG_DIR.exists():
        return DOCKER_CONFIG_DIR
    return platformdirs.user_config_path("hassette", version=f"v{VERSION.major}")


def default_data_dir(environ: Mapping[str, str], cwd: Path) -> Path:
    """Return the data directory used when no settings source sets ``data_dir``.

    Resolution order: ``HASSETTE__DATA_DIR`` or ``HASSETTE_DATA_DIR`` in `environ`, then ``/data``
    when it exists, then the platformdirs user data path. A relative env value is anchored to `cwd`.
    """
    if (env := env_lookup(environ, DATA_DIR_ENV_NAMES)) is not None:
        return anchored(env, cwd)
    if DOCKER_DATA_DIR.exists():
        return DOCKER_DATA_DIR
    return platformdirs.user_data_path("hassette", version=f"v{VERSION.major}")


def env_lookup(environ: Mapping[str, str], names: Sequence[str]) -> str | None:
    """Return the first non-empty value among `names`, matching env names case-insensitively."""
    lowered = {k.lower(): v for k, v in environ.items()}
    for name in names:
        if value := lowered.get(name):
            return value
    return None


def is_config_dir_env(name: str) -> bool:
    return name.lower() in CONFIG_DIR_ENV_NAMES


def anchored(path: str | PurePath, base: Path) -> Path:
    """Return `path` with ``~`` expanded and anchored at `base` when relative, with ``..`` collapsed.

    Symlinks are not resolved, so a path the user wrote keeps its spelling. A config file reached
    through a symlinked directory therefore anchors its relative paths at the link, whether it was
    found by search or named with ``--config-file``.
    """
    return Path(os.path.normpath(base / Path(path).expanduser()))


def file_list(files: FileList, cwd: Path) -> tuple[Path, ...]:
    if isinstance(files, str | PurePath):
        files = [files]
    return tuple(anchored(f, cwd) for f in files)


def search(dirs: Sequence[Path], name: str) -> tuple[Path, ...]:
    """Return ``dir / name`` for each dir, dropping repeats (cwd may be the default config dir)."""
    return tuple(dict.fromkeys(d / name for d in dirs))
