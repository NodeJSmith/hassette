import logging
import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import platformdirs
from packaging.version import Version
from pydantic import AliasChoices, BeforeValidator, Field, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from hassette.config.app_manifest import AppManifest
from hassette.config.sources_helper import HassetteTomlConfigSettingsSource
from hassette.const import LOG_LEVELS
from hassette.core import context as ctx
from hassette.logging_ import enable_logging
from hassette.utils.app_utils import auto_detect_app_manifests

PACKAGE_KEY = "hassette"
VERSION = Version(version(PACKAGE_KEY))

# set up logging as early as possible
LOG_LEVEL = (
    os.getenv("HASSETTE__LOG_LEVEL") or os.getenv("HASSETTE_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO"
).upper()

try:
    enable_logging(LOG_LEVEL)  # pyright: ignore[reportArgumentType]
except ValueError:
    enable_logging("INFO")

LOGGER_NAME = "hassette.config.core_config" if __name__ == "__main__" else __name__
LOGGER = logging.getLogger(LOGGER_NAME)


def get_dev_mode():
    """Check if developer mode should be enabled.

    Returns:
        bool: True if developer mode is enabled, False otherwise.
    """
    if "debugpy" in sys.modules:
        LOGGER.warning("Developer mode enabled via 'debugpy'")
        return True

    if sys.gettrace() is not None:
        LOGGER.warning("Developer mode enabled via 'sys.gettrace()'")
        return True

    if sys.flags.dev_mode:
        LOGGER.warning("Developer mode enabled via 'python -X dev'")
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


class HassetteConfig(BaseSettings):
    """Configuration for Hassette."""

    model_config = SettingsConfigDict(
        env_prefix="hassette__",
        env_file=["/config/.env", ".env", "./config/.env"],
        toml_file=["/config/hassette.toml", "hassette.toml", "./config/hassette.toml"],
        env_ignore_empty=True,
        extra="allow",
        env_nested_delimiter="__",
        coerce_numbers_to_str=True,
        validate_by_name=True,
        use_attribute_docstrings=True,
        cli_prog_name="hassette",
        cli_ignore_unknown_args=True,
        cli_parse_args=True,
        cli_kebab_case=True,
        cli_shortcuts={"token": ["t"], "base-url": ["u", "url"], "config-file": ["c"], "env-file": ["e", "env"]},
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type["BaseSettings"],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources = (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            HassetteTomlConfigSettingsSource(settings_cls),
        )
        return sources

    # note - not actually used here, reflects the options in __main__ argparser for --help
    config_file: Path | str | None = Field(default=Path("hassette.toml"))
    """Path to the configuration file."""

    # note - not actually used here, reflects the options in __main__ argparser for --help
    env_file: Path | str | None = Field(default=Path(".env"))
    """Path to the environment file."""

    dev_mode: bool = Field(default_factory=get_dev_mode)
    """Enable developer mode, which may include additional logging and features."""

    # General configuration
    log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(default="INFO")
    """Logging level for Hassette."""

    config_dir: Path = Field(default_factory=default_config_dir)
    """Directory to load/save configuration."""

    data_dir: Path = Field(default_factory=default_data_dir)
    """Directory to store Hassette data."""

    app_dir: Path = Field(default_factory=default_app_dir)
    """Directory to load user apps from."""

    # Home Assistant configuration starts here
    base_url: str = Field(default="http://127.0.0.1:8123")
    """Base URL of the Home Assistant instance"""

    token: str = Field(
        default=...,
        validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
    )
    """Access token for Home Assistant instance"""

    # has to be before apps to allow auto-detection
    auto_detect_apps: bool = Field(default=True)
    """Whether to automatically detect apps in the app directory."""

    # App configurations
    apps: dict[str, AppManifest] = Field(default_factory=dict)
    """Configuration for Hassette apps, keyed by app name."""

    # Service configurations

    startup_timeout_seconds: int = Field(default=10)
    """Length of time to wait for all Hassette resources to start before giving up."""

    app_startup_timeout_seconds: int = Field(default=20)
    """Length of time to wait for an app to start before giving up."""

    app_shutdown_timeout_seconds: int = Field(default=10)
    """Length of time to wait for an app to shut down before giving up."""

    websocket_authentication_timeout_seconds: int = Field(default=10)
    """Length of time to wait for WebSocket authentication to complete."""

    websocket_response_timeout_seconds: int = Field(default=5)
    """Length of time to wait for a response from the WebSocket."""

    websocket_connection_timeout_seconds: int = Field(default=5)
    """Length of time to wait for WebSocket connection to complete. Passed to aiohttp."""

    websocket_total_timeout_seconds: int = Field(default=30)
    """Total length of time to wait for WebSocket operations to complete. Passed to aiohttp."""

    websocket_heartbeat_interval_seconds: int = Field(default=30)
    """Interval to send ping messages to keep the WebSocket connection alive. Passed to aiohttp."""

    scheduler_min_delay_seconds: int = Field(default=1)
    """Minimum delay between scheduled jobs."""

    scheduler_max_delay_seconds: int = Field(default=30)
    """Maximum delay between scheduled jobs."""

    scheduler_default_delay_seconds: int = Field(default=15)
    """Default delay between scheduled jobs."""

    run_sync_timeout_seconds: int = Field(default=6)
    """Default timeout for synchronous function calls."""

    run_health_service: bool = Field(default=True)
    """Whether to run the health service for container healthchecks."""

    health_service_port: int | None = Field(default=8126)
    """Port to run the health service on, ignored if run_health_service is False."""

    file_watcher_debounce_milliseconds: int = Field(default=3_000)
    """Debounce time for file watcher events in milliseconds."""

    file_watcher_step_milliseconds: int = Field(default=500)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""

    task_cancellation_timeout_seconds: int = Field(default=5)
    """Length of time to wait for tasks to cancel before forcing."""

    # Service log levels

    bus_service_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the event bus service. Defaults to INFO or the value of log_level."""

    scheduler_service_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the scheduler service. Defaults to INFO or the value of log_level."""

    app_handler_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the app handler service. Defaults to INFO or the value of log_level."""

    health_service_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the health service. Defaults to INFO or the value of log_level."""

    websocket_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the WebSocket service. Defaults to INFO or the value of log_level."""

    service_watcher_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the service watcher. Defaults to INFO or the value of log_level."""

    file_watcher_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for the file watcher service. Defaults to INFO or the value of log_level."""

    task_bucket_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Logging level for task buckets. Defaults to INFO or the value of log_level."""

    apps_log_level: Annotated[LOG_LEVELS, BeforeValidator(str.upper)] = Field(
        default_factory=lambda data: data.get("log_level", "INFO")
    )
    """Default logging level for apps, can be overridden in app initialization. Defaults to INFO or the value\
        of log_level."""

    log_all_events: bool = Field(default=False)
    """Whether to include all events in bus debug logging. Should be used sparingly. Defaults to False."""

    log_all_hass_events: bool = Field(default_factory=lambda data: data.get("log_all_events", False))
    """Whether to include all Home Assistant events in bus debug logging. Defaults to False or the\
        value of log_all_events."""

    log_all_hassette_events: bool = Field(default_factory=lambda data: data.get("log_all_events", False))
    """Whether to include all Hassette events in bus debug logging. Defaults to False or the
        value of log_all_events."""

    # event bus filters

    bus_excluded_domains: tuple[str, ...] = Field(default_factory=tuple)
    """Domains whose events should be skipped by the bus; supports glob patterns (e.g. 'sensor', 'media_*')."""

    bus_excluded_entities: tuple[str, ...] = Field(default_factory=tuple)
    """Entity IDs whose events should be skipped by the bus; supports glob patterns."""

    # production mode settings

    allow_reload_in_prod: bool = Field(default=False)
    """Whether to allow reloading apps in production mode. Defaults to False."""

    allow_only_app_in_prod: bool = Field(default=False)
    """Whether to allow the `only_app` decorator in production mode. Defaults to False."""

    @property
    def env_files(self) -> set[Path]:
        """Return a list of environment files that Pydantic will check."""
        return filter_paths_to_unique_existing(self.model_config.get("env_file", []))

    @property
    def toml_files(self) -> set[Path]:
        """Return a list of toml files that Pydantic will check."""
        return filter_paths_to_unique_existing(self.model_config.get("toml_file", []))

    def get_watchable_files(self) -> set[Path]:
        """Return a list of files to watch for changes."""

        files = self.env_files | self.toml_files
        files.add(self.app_dir.resolve())

        # just add everything from here, since we'll filter it to only existing and remove duplicates later
        for app in self.apps.values():
            with suppress(FileNotFoundError):
                files.add(app.get_full_path())
                files.add(app.app_dir)

        files = filter_paths_to_unique_existing(files)

        return files

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return the headers required for authentication."""
        return {"Authorization": f"Bearer {self.token}"}

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers for API requests."""
        headers = self.auth_headers.copy()
        headers["Content-Type"] = "application/json"
        return headers

    @property
    def truncated_token(self) -> str:
        """Return a truncated version of the token for display purposes."""
        return f"{self.token[:6]}...{self.token[-6:]}"

    @model_validator(mode="after")
    def validate_hassette_config(self) -> "HassetteConfig":
        self.app_dir = self.app_dir.resolve()
        self.config_dir = self.config_dir.resolve()
        self.data_dir = self.data_dir.resolve()

        LOGGER.info("Hassette version: %s", VERSION)

        LOGGER.debug("Hassette configuration: %s", self.model_dump_json(indent=4))

        active_apps = [app for app in self.apps.values() if app.enabled]
        if active_apps:
            LOGGER.info("Active apps: %s", active_apps)
        else:
            LOGGER.info("No active apps found.")

        inactive_apps = [app for app in self.apps.values() if not app.enabled]
        if inactive_apps:
            LOGGER.info("Inactive apps: %s", inactive_apps)

        return self

    @field_validator("apps", mode="before")
    @classmethod
    def validate_apps(cls, values: dict[str, Any], info: ValidationInfo) -> dict[str, Any]:
        """Sets the app_dir in each app manifest if not already set."""
        return validate_apps(values, info.data.get("app_dir"), info.data.get("auto_detect_apps", True))

    def model_post_init(self, context: Any):
        ctx.HASSETTE_CONFIG.set(self)

        enable_logging(self.log_level)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)

        tz = os.getenv("TZ")
        if tz:
            LOGGER.info("Using timezone from environment variable TZ: %s", tz)

    def reload(self):
        """Reload the configuration from all sources."""
        # we don't need to pass the base_config here, since it's already set on self
        self.__init__()  # type: ignore

    @classmethod
    def get_config(cls) -> "HassetteConfig":
        """Get the global configuration instance."""

        inst = ctx.HASSETTE_CONFIG.get(None)
        if inst is not None:
            return inst

        raise RuntimeError("HassetteConfig instance not initialized yet.")


def filter_paths_to_unique_existing(value: Sequence[str | Path | None] | str | Path | None | set[Path]) -> set[Path]:
    """Filter the provided paths to only include unique existing paths.

    Args:
        value (list[str]): List of file paths as strings.

    Returns:
        list[Path]: List of existing file paths as Path objects.

    Raises:
        ValueError: If any of the provided paths do not exist.
    """
    value = [value] if isinstance(value, str | Path | None) else value

    paths = set(Path(v).resolve() for v in value if v)
    paths = set(p for p in paths if p.exists())

    return paths


def validate_apps(values: dict[str, Any], app_dir: Path | None, auto_detect: bool) -> dict[str, Any]:
    """Sets the app_dir in each app manifest if not already set.

    Args:
        values (dict[str, Any]): The app configurations to validate.
        app_dir (Path | None): The application directory.
        auto_detect (bool): Whether to automatically detect apps.

    Returns:
        dict[str, Any]: The validated app configurations.

    This is separated from the HassetteConfig class to allow easier testing.

    """
    required_keys = {"filename", "class_name"}
    missing_required = {k: v for k, v in values.items() if isinstance(v, dict) and not required_keys.issubset(v)}
    if missing_required:
        LOGGER.warning(
            "The following apps are missing required keys (%s) and will be ignored: %s",
            ", ".join(required_keys),
            list(missing_required.keys()),
        )
        for k in missing_required:
            values.pop(k)

    if not app_dir:
        return values

    paths: set[Path] = set()

    for k, v in values.items():
        if not isinstance(v, dict):
            continue
        v["app_key"] = k
        filename = Path(v["filename"])

        # handle missing file extensions
        if not filename.suffix:
            LOGGER.debug("Filename %s for app %s has no extension, assuming .py", v["filename"], v["app_key"])
            v["filename"] = filename.with_suffix(".py").as_posix()

        if "app_dir" not in v or not v["app_dir"]:
            LOGGER.debug("Setting app_dir for app %s to %s", v["filename"], app_dir)
            v["app_dir"] = app_dir
        path = Path(v["app_dir"]) / str(v["filename"])
        paths.add(path.resolve())

    if not auto_detect:
        return values

    auto_detected_apps = auto_detect_app_manifests(app_dir, paths)
    for k, v in auto_detected_apps.items():
        full_path = v.app_dir / v.filename
        LOGGER.info("Auto-detected app %s from %s", k, full_path)
        if k in values:
            LOGGER.debug("Skipping auto-detected app %s as it conflicts with manually configured app", k)
            continue
        values[k] = {
            "filename": v.filename,
            "class_name": v.class_name,
            "app_dir": v.app_dir,
            "app_key": v.app_key,
            "enabled": v.enabled,
        }

    return values


if __name__ == "__main__":
    # quick test
    config = HassetteConfig()
    print(config.model_dump_json(indent=4))
