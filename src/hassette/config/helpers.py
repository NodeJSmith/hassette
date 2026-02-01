import logging
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path
from typing import cast, get_args
from warnings import warn

import platformdirs
from packaging.version import Version

from hassette import context
from hassette.exceptions import HassetteNotInitializedError
from hassette.types.types import LOG_LEVEL_TYPE

LOG_LEVEL_VALUES = get_args(LOG_LEVEL_TYPE)

PACKAGE_KEY = "hassette"
VERSION = Version(version(PACKAGE_KEY))


def get_dev_mode() -> bool:
    """Check if developer mode should be enabled.

    Returns:
        True if developer mode is enabled, False otherwise.
    """
    with suppress(HassetteNotInitializedError):
        curr_config = context.get_hassette_config()
        # not sure if we can even change this during runtime, but for now we are not
        # going to allow it
        return curr_config.dev_mode

    logger = logging.getLogger(__name__)

    enabled = False
    reason = None

    if "debugpy" in sys.modules:
        enabled = True
        reason = "debugpy"
    elif sys.gettrace() is not None:
        enabled = True
        reason = "sys.gettrace()"
    elif sys.flags.dev_mode:
        enabled = True
        reason = "python -X dev"

    if enabled:
        logger.setLevel(get_log_level())
        logger.info("Developer mode enabled (%s)", reason)

    return enabled


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


def warn_log_level_not_valid(log_level: str, fallback_value: LOG_LEVEL_TYPE) -> None:
    warn(
        f"Log level {log_level!r} is not valid, defaulting to {fallback_value!r}. ",
        skip_file_prefixes=("hassette.config.helpers", "pydantic"),
    )


def get_log_level() -> LOG_LEVEL_TYPE:
    log_level = os.getenv("HASSETTE__LOG_LEVEL") or os.getenv("HASSETTE_LOG_LEVEL") or os.getenv("LOG_LEVEL")
    return coerce_log_level(log_level, "INFO")


def coerce_log_level(value: str | LOG_LEVEL_TYPE | None, fallback: LOG_LEVEL_TYPE) -> LOG_LEVEL_TYPE:
    """Coerce a log level value to a LOG_LEVEL_TYPE string.

    Args:
        value: The log level value to coerce.
        fallback: The fallback log level to use if the input is invalid.

    Returns:
        The coerced log level as a LOG_LEVEL_TYPE string or the fallback value.
    """
    if value is None:
        return fallback

    if not isinstance(value, str):
        warn_log_level_not_valid(str(value), fallback)
        return fallback

    value = value.upper()

    if value not in LOG_LEVEL_VALUES:
        warn_log_level_not_valid(value, fallback)
        return fallback

    return cast("LOG_LEVEL_TYPE", value)


def log_level_default_factory(data: dict[str, LOG_LEVEL_TYPE | None]) -> LOG_LEVEL_TYPE:
    """Default factory for log level fields.

    Returns the log_level from the data dictionary if present, otherwise
    falls back to the environment variable-based log level.

    Args:
        data: Dictionary containing field values during model initialization.

    Returns:
        The determined log level.
    """
    return coerce_log_level(data.get("log_level"), "INFO")
