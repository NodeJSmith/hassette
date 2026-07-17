from contextlib import suppress
from logging import getLogger
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from hassette import context as ctx
from hassette.config.classes import AppManifest, ExcludeExtrasMixin, HassetteTomlConfigSettingsSource
from hassette.config.defaults import (
    ENV_FILE_LOCATIONS,
    TOML_FILE_LOCATIONS,
    get_defaults_dict,
)
from hassette.config.helpers import (
    default_config_dir,
    default_data_dir,
    filter_paths_to_unique_existing,
    get_dev_mode,
)
from hassette.config.models import (
    AppsConfig,
    BlockingIODetectionConfig,
    DatabaseConfig,
    FileWatcherConfig,
    LifecycleConfig,
    LoggingConfig,
    SchedulerConfig,
    WebApiConfig,
    WebSocketConfig,
)
from hassette.types.enums import ForgottenAwaitBehavior
from hassette.types.types import FRAMEWORK_APP_KEY_PREFIX, AppDict, is_framework_key
from hassette.utils.app_utils import autodetect_apps, clean_app

LOGGER = getLogger(__name__)

TOKEN_SHORT_THRESHOLD = 8
TOKEN_MEDIUM_THRESHOLD = 12
TOKEN_SHORT_PREFIX_LENGTH = 3
TOKEN_LONG_PREFIX_LENGTH = 6


class HassetteConfig(ExcludeExtrasMixin, BaseSettings):
    """Configuration for Hassette."""

    model_config = SettingsConfigDict(
        env_prefix="hassette__",
        env_file=ENV_FILE_LOCATIONS,
        toml_file=TOML_FILE_LOCATIONS,
        env_ignore_empty=True,
        extra="allow",
        env_nested_delimiter="__",
        coerce_numbers_to_str=True,
        validate_by_name=True,
        use_attribute_docstrings=True,
        validate_assignment=True,
        cli_parse_args=False,
        nested_model_default_partial_update=True,
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

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    """Database storage, retention, and operational settings."""

    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    """WebSocket connection, retry, and recovery timing settings."""

    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    """Logging level, format, queue, and per-service log-level settings."""

    lifecycle: LifecycleConfig = Field(default_factory=LifecycleConfig)
    """Startup, shutdown, and per-operation timeout settings."""

    web_api: WebApiConfig = Field(default_factory=WebApiConfig)
    """Web API and UI server settings."""

    apps: AppsConfig = Field(default_factory=AppsConfig)
    """App directory, auto-detection, and manifest settings."""

    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    """Scheduler delay, threshold, and job-timeout settings."""

    file_watcher: FileWatcherConfig = Field(default_factory=FileWatcherConfig)
    """File watcher debounce, step, and enable/disable settings."""

    blocking_io: BlockingIODetectionConfig = Field(default_factory=BlockingIODetectionConfig)
    """Blocking-I/O detection settings for the shared event loop."""

    timezone: str | None = Field(default=None)
    """IANA timezone name (e.g. ``"America/Chicago"``) used for all wall-clock
    operations: scheduler trigger resolution, event timestamp conversion, and
    state model datetime fields.

    When ``None`` (default), the system process timezone is used. Set this when
    the hassette process runs in a different timezone than Home Assistant (e.g.
    Docker containers running UTC while HA is configured for a local zone)."""

    # note - not actually used here, reflects the --config-file / --env-file flags on the cyclopts default command
    config_file: Path | str | None = Field(default=Path("hassette.toml"))
    """Path to the configuration file."""

    # note - not actually used here, reflects the --config-file / --env-file flags on the cyclopts default command
    env_file: Path | str | None = Field(default=Path(".env"))
    """Path to the environment file."""

    dev_mode: bool = Field(default_factory=get_dev_mode)
    """Enable developer mode, which may include additional logging and features."""

    # Home Assistant connection — cross-cutting
    base_url: str = Field(default="http://127.0.0.1:8123", json_schema_extra={"ui": {"label": "Base URL"}})
    """Base URL of the Home Assistant instance"""

    verify_ssl: bool = Field(default=True, json_schema_extra={"ui": {"label": "Verify SSL"}})
    """Whether to verify SSL certificates when connecting to Home Assistant. Useful to disable for self-signed
    certificates."""

    token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
    )
    """Access token for Home Assistant instance.

    Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs
    and string representations.  Unwrap with ``token.get_secret_value()`` when
    the plaintext is required (e.g. HTTP auth headers, WebSocket auth payload).
    """

    config_dir: Path = Field(default_factory=default_config_dir)
    """Directory to load/save configuration."""

    data_dir: Path = Field(default_factory=default_data_dir)
    """Directory to store Hassette data."""

    import_dot_env_files: bool = Field(default=True)
    """Whether to import .env files specified in env_files. With this disabled, the .env file provided will only
    be used for loading settings. With this enabled, the .env files will also be loaded into os.environ."""

    run_app_precheck: bool = Field(default=True)
    """Whether to run the app precheck before starting Hassette. This is recommended, but if any apps fail to load
    then Hassette will not start."""

    allow_startup_if_app_precheck_fails: bool = Field(default=False)
    """Whether to allow Hassette to start even if the app precheck fails. This is generally not recommended."""

    hassette_event_buffer_size: int = Field(default=1000)
    """Buffer capacity of the internal anyio memory channel used to route events to the bus."""

    default_cache_ttl: int | None = Field(default=None)
    """Default TTL for cache entries in seconds. None means entries persist indefinitely."""

    strict_lifecycle: bool = Field(default=False)
    """Enable strict validation for lifecycle transitions, connection state, and registries.

    Controls three subsystems uniformly:
    - Resource lifecycle: invalid ResourceStatus transitions raise InvalidLifecycleTransitionError
    - WebSocket connection: invalid ConnectionState transitions raise InvalidLifecycleTransitionError
    - Registry validation: startup issues raise RegistryValidationError

    When False (default), all three subsystems log WARNING instead of raising.
    The test harness sets this to True by default."""

    asyncio_debug_mode: bool = Field(default=False)
    """Whether to enable asyncio debug mode."""

    state_proxy_poll_interval_seconds: int = Field(default=30)
    """Interval in seconds to poll the state proxy for updates."""

    disable_state_proxy_polling: bool = Field(default=False)
    """Whether to disable polling for the state proxy. Defaults to False."""

    bus_excluded_domains: tuple[str, ...] = Field(default_factory=tuple)
    """Domains whose events should be skipped by the bus; supports glob patterns (e.g. 'sensor', 'media_*')."""

    bus_excluded_entities: tuple[str, ...] = Field(default_factory=tuple)
    """Entity IDs whose events should be skipped by the bus; supports glob patterns."""

    allow_reload_in_prod: bool = Field(default=False)
    """Whether to enable the file watcher for automatic app reloads in production mode.

    When True, file changes trigger automatic app reloads (same as dev_mode).
    Manual app management (start/stop/reload via API) is always available
    regardless of this setting. Defaults to False.
    """

    allow_only_app_in_prod: bool = Field(default=False)
    """Whether to allow the `only_app` decorator in production mode. Defaults to False."""

    forgotten_await_behavior: ForgottenAwaitBehavior | None = Field(default=None)
    """Global default for forgotten-await detection behavior.

    When ``None`` (default), the effective behavior is ``"warn"``.  Per-app
    ``AppConfig.forgotten_await_behavior`` overrides this when set.  Set to ``"ignore"``
    to suppress warnings globally, or ``"error"`` to escalate via ``filterwarnings("error")``."""

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
        files.add(self.apps.directory.resolve())

        # just add everything from here, since we'll filter it to only existing and remove duplicates later
        for app_manifest in self.apps.manifests.values():
            with suppress(FileNotFoundError):
                files.add(app_manifest.full_path)
                files.add(app_manifest.app_dir)

        files = filter_paths_to_unique_existing(files)

        return files

    @property
    def auth_headers(self) -> dict[str, str]:
        """Return the headers required for authentication.

        Calls :meth:`~pydantic.SecretStr.get_secret_value` to unwrap the token
        so the plaintext reaches the Authorization header, not the masked repr.
        """
        if self.token is None:
            return {}
        return {"Authorization": f"Bearer {self.token.get_secret_value()}"}

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers for API requests."""
        return {**self.auth_headers, "Content-Type": "application/json"}

    @property
    def truncated_token(self) -> str:
        """Return a truncated version of the token for display purposes.

        Calls :meth:`~pydantic.SecretStr.get_secret_value` to obtain the
        plaintext before slicing — ``SecretStr`` is not subscriptable.
        """
        if self.token is None:
            return "<not set>"
        raw = self.token.get_secret_value()
        if len(raw) < TOKEN_SHORT_THRESHOLD:
            return "***"
        if len(raw) <= TOKEN_MEDIUM_THRESHOLD:
            return f"{raw[:TOKEN_SHORT_PREFIX_LENGTH]}***"
        return f"{raw[:TOKEN_LONG_PREFIX_LENGTH]}...{raw[-TOKEN_LONG_PREFIX_LENGTH:]}"

    @model_validator(mode="after")
    def validate_log_retention_days(self) -> "HassetteConfig":
        """Ensure logging.log_retention_days <= database.retention_days.

        Log records reference executions; allowing log records to outlive
        the execution records that produced them would break referential
        integrity semantics even though the FK is not enforced at the DB level.
        """
        if self.logging.log_retention_days > self.database.retention_days:
            raise ValueError(
                f"logging.log_retention_days ({self.logging.log_retention_days}) must be <= "
                f"database.retention_days ({self.database.retention_days})"
            )
        return self

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (KeyError, ValueError):
            raise ValueError(
                f"Invalid timezone: {value!r}. Use an IANA timezone name (e.g. 'America/Chicago', 'Europe/London')."
            ) from None
        return value

    @field_validator("config_dir", "data_dir", mode="after")
    @classmethod
    def resolve_paths(cls, value: Path) -> Path:
        """Resolve paths to absolute without creating directories.

        Directory creation is deferred to server startup (Hassette.wire_services)
        so that read-only CLI commands don't produce filesystem side effects.
        """
        return value.resolve()

    def ensure_directories(self) -> None:
        """Create config_dir and data_dir if they don't exist."""
        for directory in (self.config_dir, self.data_dir):
            if not directory.exists():
                LOGGER.debug("Creating directory %s as it does not exist", directory)
                directory.mkdir(parents=True, exist_ok=True)

    def reload(self) -> None:
        """Reload the configuration from all sources."""
        # see: https://docs.pydantic.dev/latest/concepts/pydantic_settings/#in-place-reloading
        self.__init__()
        self.set_validated_app_manifests()

    def model_post_init(self, *args: Any) -> None:
        """Set default values for any unset fields after initialization."""
        default_str = "default (dev)" if self.dev_mode else "default (prod)"
        defaults = get_defaults_dict(dev=self.dev_mode)

        # Apply root-level flat defaults (e.g. dev_mode, allow_startup_if_app_precheck_fails,
        # state_proxy_poll_interval_seconds)
        for fname in type(self).model_fields:
            if fname in self.model_fields_set or fname not in defaults:
                continue
            # Skip nested group names — they are handled below
            if fname in NESTED_GROUPS:
                continue
            default_value = defaults[fname]
            LOGGER.debug("Setting %s for unset field %s: %s", default_str, fname, default_value)
            setattr(self, fname, default_value)

        # Apply nested group defaults (e.g. [hassette.websocket], [hassette.scheduler])
        for group_name in NESTED_GROUPS:
            if group_name not in defaults or group_name in self.model_fields_set:
                continue
            group_defaults = defaults[group_name]
            if not isinstance(group_defaults, dict):
                continue
            group_obj = getattr(self, group_name)
            for sub_field, sub_value in group_defaults.items():
                LOGGER.debug(
                    "Setting %s for unset nested field %s.%s: %s",
                    default_str,
                    group_name,
                    sub_field,
                    sub_value,
                )
                setattr(group_obj, sub_field, sub_value)

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

        for k, v in self.apps.apps.copy().items():
            if not isinstance(v, dict):
                continue
            try:
                v = clean_app(k, v, self.apps.directory)
            except (KeyError, TypeError):
                LOGGER.warning("Skipping app %r: missing required keys (filename or class_name)", k)
                continue
            cleaned_apps_dict[k] = v

            # track known paths
            known_paths.add(v["full_path"])

        if self.apps.autodetect:
            autodetected_apps = autodetect_apps(self.apps.directory, known_paths, set(self.apps.exclude_dirs))
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
            if is_framework_key(k):
                raise ValueError(
                    f"App key {k!r} is reserved for framework internals "
                    f"(reserved prefix: '{FRAMEWORK_APP_KEY_PREFIX}'). "
                    f"Rename the app in your configuration (source: {v.get('full_path', 'unknown')})."
                )
            app_manifest_dict[k] = AppManifest.model_validate(v)

        self.apps.manifests = app_manifest_dict

        warn_on_cache_key_collisions(app_manifest_dict)


def resolve_cache_keys(app_key: str, manifest: AppManifest) -> list[str]:
    """Return the resolved cache_key(s) for every instance of *manifest*.

    When ``manifest.cache_key`` is explicitly set, all instances share that single value
    (the index is not appended). When unset, each instance gets its own default key
    ``{app_key}/{idx}`` derived from its position in ``app_config``.
    """
    if manifest.cache_key:
        return [manifest.cache_key]

    instance_count = len(manifest.app_config) if isinstance(manifest.app_config, list) else 1
    return [f"{app_key}/{idx}" for idx in range(instance_count)]


def warn_on_cache_key_collisions(manifests: dict[str, AppManifest]) -> None:
    """Log a WARNING when different apps resolve to the same cache_key.

    Two apps sharing a resolved cache_key intentionally (e.g. one app renamed to preserve
    its predecessor's cache) is allowed, but is usually a configuration mistake — this
    surfaces it at config-load time rather than as silent cross-app cache contamination.
    """
    owners_by_resolved_key: dict[str, set[str]] = {}
    for app_key, manifest in manifests.items():
        for resolved_key in resolve_cache_keys(app_key, manifest):
            owners_by_resolved_key.setdefault(resolved_key, set()).add(app_key)

    for resolved_key, owners in owners_by_resolved_key.items():
        if len(owners) > 1:
            LOGGER.warning(
                "Multiple apps resolve to the same cache_key %r: %s. If this is unintentional, "
                "set an explicit, unique `cache_key` on each app to avoid cache cross-contamination.",
                resolved_key,
                sorted(owners),
            )


NESTED_GROUPS: dict[str, type] = {
    name: field.annotation
    for name, field in HassetteConfig.model_fields.items()
    if isinstance(field.annotation, type) and issubclass(field.annotation, ExcludeExtrasMixin)
}
