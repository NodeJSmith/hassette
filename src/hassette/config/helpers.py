import logging
import os
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import cast

import platformdirs
from packaging.version import Version

from hassette.types.types import LOG_LEVELS

PACKAGE_KEY = "hassette"
VERSION = Version(version(PACKAGE_KEY))


def get_log_level() -> LOG_LEVELS:
    log_level = (
        os.getenv("HASSETTE__LOG_LEVEL") or os.getenv("HASSETTE_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO"
    ).upper()
    if log_level not in list(LOG_LEVELS.__args__):
        logging.getLogger(__name__).warning("Log level %r is not valid, defaulting to INFO", log_level)
        log_level = "INFO"
    return cast("LOG_LEVELS", log_level)


def get_dev_mode():
    """Check if developer mode should be enabled.

    Returns:
        True if developer mode is enabled, False otherwise.
    """
    logger = logging.getLogger(__name__)
    if "debugpy" in sys.modules:
        logger.warning("Developer mode enabled via 'debugpy'")
        return True

    if sys.gettrace() is not None:
        logger.warning("Developer mode enabled via 'sys.gettrace()'")
        return True

    if sys.flags.dev_mode:
        logger.warning("Developer mode enabled via 'python -X dev'")
        return True

    return False


def default_config_dir() -> Path:
    """Return the first found config directory based on environment variables or defaults.

    Will return the first of:
    - HASSETTE__CONFIG_DIR environment variable
    - HASSETTE_CONFIG_DIR environment variable
    - /config (for docker)
    - platformdirs user config path

    """

    if env := os.getenv("HASSETTE__CONFIG_DIR", os.getenv("HASSETTE_CONFIG_DIR")):
        return Path(env)
    docker = Path("/config")
    if docker.exists():
        return docker
    return platformdirs.user_config_path("hassette", version=f"v{VERSION.major}")


def default_data_dir() -> Path:
    """Return the first found data directory based on environment variables or defaults.

    Will return the first of:
    - HASSETTE__DATA_DIR environment variable
    - HASSETTE_DATA_DIR environment variable
    - /data (for docker)
    - platformdirs user data path

    """

    if env := os.getenv("HASSETTE__DATA_DIR", os.getenv("HASSETTE_DATA_DIR")):
        return Path(env)
    docker = Path("/data")
    if docker.exists():
        return docker
    return platformdirs.user_data_path("hassette", version=f"v{VERSION.major}")


def default_app_dir() -> Path:
    """Return the first found app directory based on environment variables or defaults.

    Will return the first of:
    - HASSETTE__APP_DIR environment variable
    - HASSETTE_APP_DIR environment variable
    - /apps (for docker)
    - platformdirs user app path

    """

    if env := os.getenv("HASSETTE__APP_DIR", os.getenv("HASSETTE_APP_DIR")):
        return Path(env)
    docker = Path("/apps")
    if docker.exists():
        return docker
    return Path.cwd() / "apps"  # relative to where the program is run


def filter_paths_to_unique_existing(value: Sequence[str | Path | None] | str | Path | None | set[Path]) -> set[Path]:
    """Filter the provided paths to only include unique existing paths.

    Args:
        value: List of file paths as strings.

    Returns:
        List of existing file paths as Path objects.

    Raises:
        ValueError: If any of the provided paths do not exist.
    """
    value = [value] if isinstance(value, str | Path | None) else value

    paths = set(Path(v).resolve() for v in value if v)
    paths = set(p for p in paths if p.exists())

    return paths


def coerce_log_level(value: str | LOG_LEVELS | None) -> LOG_LEVELS | None:
    if value is None:
        return None

    if not isinstance(value, str):
        return None

    value = value.upper()

    if value not in list(LOG_LEVELS.__args__):
        return None

    return cast("LOG_LEVELS", value)


def log_level_default_factory(data: dict[str, LOG_LEVELS | None]) -> LOG_LEVELS:
    """Default factory for log level field."""
    return data.get("log_level") or get_log_level()
