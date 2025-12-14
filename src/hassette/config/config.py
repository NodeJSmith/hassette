import logging
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, BeforeValidator, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from hassette import context as ctx
from hassette.config.classes import AppManifest, HassetteTomlConfigSettingsSource
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT, get_default_dict
from hassette.config.helpers import (
    coerce_log_level,
    default_app_dir,
    default_config_dir,
    default_data_dir,
    filter_paths_to_unique_existing,
    get_dev_mode,
    log_level_default_factory,
)
from hassette.types.types import LOG_LEVELS, AppDict, RawAppDict
from hassette.utils.app_utils import autodetect_apps, clean_app

LOGGER_NAME = "hassette.config.config" if __name__ == "__main__" else __name__
LOGGER = logging.getLogger(LOGGER_NAME)

LOG_ANNOTATION = Annotated[LOG_LEVELS, BeforeValidator(coerce_log_level)]


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
        validate_assignment=True,
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
    log_level: LOG_ANNOTATION = Field(default="INFO")
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

    verify_ssl: bool = Field(default=True)
    """Whether to verify SSL certificates when connecting to Home Assistant. Useful to disable for self-signed
    certificates."""

    token: str = Field(
        default=...,
        validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
    )
    """Access token for Home Assistant instance"""

    # has to be before apps to allow auto-detection
    autodetect_apps: bool = Field(default=True, validation_alias=AliasChoices("autodetect_apps", "auto_detect_apps"))
    """Whether to automatically detect apps in the app directory."""

    extend_autodetect_exclude_dirs: tuple[str, ...] = Field(default_factory=tuple)
    """Additional directories to exclude when auto-detecting apps in the app directory."""

    autodetect_exclude_dirs: tuple[str, ...] = Field(
        default_factory=lambda data: (
            *data.get("extend_autodetect_exclude_dirs", ()),
            *AUTODETECT_EXCLUDE_DIRS_DEFAULT,
        )
    )
    """Directories to exclude when auto-detecting apps in the app directory. Prefer `extend_autodetect_exclude_dirs`
    to avoid removing the defaults."""

    # App configurations
    apps: dict[str, RawAppDict] = Field(default_factory=dict)
    """Raw configuration for Hassette apps, keyed by app name."""

    app_manifests: dict[str, AppManifest] = Field(default_factory=dict)
    """Validated app manifests, keyed by app name."""

    # Service configurations

    import_dot_env_files: bool = Field(default=True)
    """Whether to import .env files specified in env_files. With this disabled, the .env file provided will only
    be used for loading settings. With this enabled, the .env files will also be loaded into os.environ."""

    run_app_precheck: bool = Field(default=True)
    """Whether to run the app precheck before starting Hassette. This is recommended, but if any apps fail to load
    then Hassette will not start."""

    allow_startup_if_app_precheck_fails: bool = Field(default=False)
    """Whether to allow Hassette to start even if the app precheck fails. This is generally not recommended."""

    startup_timeout_seconds: int = Field(default=10)
    """Length of time to wait for all Hassette resources to start before giving up."""

    app_startup_timeout_seconds: int = Field(default=20)
    """Length of time to wait for an app to start before giving up."""

    app_shutdown_timeout_seconds: int = Field(default=10)
    """Length of time to wait for an app to shut down before giving up."""

    resource_shutdown_timeout_seconds: int = Field(
        default_factory=lambda data: data.get("app_shutdown_timeout_seconds", 10)
    )
    """Length of time to wait for a resource to shut down before giving up. Defaults to app_shutdown_timeout_seconds."""

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

    default_cache_size: int = Field(default=100 * 1024 * 1024)
    """Default size limit for caches in bytes. Defaults to 100 MiB."""

    asyncio_debug_mode: bool = Field(default=False)
    """Whether to enable asyncio debug mode."""

    # Service log levels

    bus_service_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the event bus service. Defaults to INFO or the value of log_level."""

    scheduler_service_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the scheduler service. Defaults to INFO or the value of log_level."""

    app_handler_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the app handler service. Defaults to INFO or the value of log_level."""

    health_service_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the health service. Defaults to INFO or the value of log_level."""

    websocket_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the WebSocket service. Defaults to INFO or the value of log_level."""

    service_watcher_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the service watcher. Defaults to INFO or the value of log_level."""

    file_watcher_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the file watcher service. Defaults to INFO or the value of log_level."""

    task_bucket_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for task buckets. Defaults to INFO or the value of log_level."""

    apps_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Default logging level for apps, can be overridden in app initialization. Defaults to INFO or the value\
        of log_level."""

    state_proxy_log_level: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the state proxy resource. Defaults to INFO or the value of log_level."""

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
        for app in self.app_manifests.values():
            with suppress(FileNotFoundError):
                files.add(app.full_path)
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

    @field_validator("apps", mode="before")
    @classmethod
    def remove_incomplete_apps(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Remove any apps that are missing required fields before validation."""

        required_keys = {"filename", "class_name"}
        missing_required = {k: v for k, v in value.items() if isinstance(v, dict) and not required_keys.issubset(v)}
        if missing_required:
            LOGGER.warning(
                "The following apps are missing required keys (%s) and will be ignored: %s",
                ", ".join(required_keys),
                list(missing_required.keys()),
            )
            for k in missing_required:
                value.pop(k)

        return value

    @field_validator("app_dir", "config_dir", "data_dir", mode="after")
    @classmethod
    def resolve_paths(cls, value: Path) -> Path:
        """Ensure that paths are resolved to absolute paths."""
        resolved = value.resolve()
        if not resolved.exists():
            LOGGER.debug("Creating directory %s as it does not exist", resolved)
            resolved.mkdir(parents=True, exist_ok=True)
        return resolved

    def reload(self):
        """Reload the configuration from all sources."""
        # see: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        self.__init__()
        self.set_validated_app_manifests()

    def model_post_init(self, *args):
        """Set default values for any unset fields after initialization."""
        default_str = "default (dev)" if self.dev_mode else "default (prod)"
        defaults = get_default_dict(dev=self.dev_mode)

        for fname in type(self).model_fields:
            if fname in self.model_fields_set or fname not in defaults:
                continue
            default_value = defaults[fname]
            LOGGER.debug("Setting %s for unset field %s: %s", default_str, fname, default_value)
            setattr(self, fname, default_value)

    @classmethod
    def get_config(cls) -> "HassetteConfig":
        """Get the global configuration instance.

        Raises:
            HassetteNotInitializedError: If the Hassette instance is not initialized.
        """
        return ctx.get_hassette_config()

    def set_validated_app_manifests(self):
        """Cleans up and validates the apps configuration, including auto-detection."""
        cleaned_apps_dict: dict[str, AppDict] = {}

        # track known paths to simplify dupe detection during auto-detect
        known_paths: set[Path] = set()

        for k, v in self.apps.copy().items():
            if not isinstance(v, dict):
                continue
            v = clean_app(k, v, self.app_dir)
            cleaned_apps_dict[k] = v

            # track known paths
            known_paths.add(v["full_path"])

        if self.autodetect_apps:
            autodetected_apps = autodetect_apps(self.app_dir, known_paths, set(self.autodetect_exclude_dirs))
            for k, v in autodetected_apps.items():
                app_dir = v["app_dir"]
                full_path = app_dir / v["filename"]
                LOGGER.debug("Auto-detected app %s from %s", k, full_path)
                if k in cleaned_apps_dict:
                    LOGGER.debug("Skipping auto-detected app %s as it conflicts with manually configured app", k)
                    continue
                cleaned_apps_dict[k] = v
                known_paths.add(full_path.resolve())

        app_manifest_dict: dict[str, AppManifest] = {}
        for k, v in cleaned_apps_dict.items():
            app_manifest_dict[k] = AppManifest.model_validate(v)

        self.app_manifests = app_manifest_dict


if __name__ == "__main__":
    # quick test
    config = HassetteConfig()
    print(config.model_dump_json(indent=4))
