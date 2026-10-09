import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from logging import getLogger
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, PrivateAttr, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, InitSettingsSource, PydanticBaseSettingsSource, SettingsConfigDict

from hassette import context as ctx
from hassette.config.build import ACTIVE_BUILD, ConfigBuild, default_build_data_dir, open_build
from hassette.config.checks import check_config_dir_not_in_files, check_explicit_locations, check_unknown_keys
from hassette.config.classes import AppManifest, ExcludeExtrasMixin, local_overlay_paths, unsafe_cache_path_reason
from hassette.config.defaults import get_defaults_dict
from hassette.config.helpers import filter_paths_to_unique_existing, get_dev_mode
from hassette.config.locations import (
    ENV_NESTED_DELIMITER,
    SETTINGS_ENV_PREFIX,
    ConfigLocations,
    FileList,
    default_config_dir,
    resolve_locations,
)
from hassette.config.models import (
    AppsConfig,
    BlockingIODetectionConfig,
    CliConfig,
    DatabaseConfig,
    FileWatcherConfig,
    LifecycleConfig,
    LoggingConfig,
    SchedulerConfig,
    WebApiConfig,
    WebSocketConfig,
)
from hassette.config.sources import (
    FileDotEnvSettingsSource,
    HassetteTomlConfigSettingsSource,
    SnapshotEnvSettingsSource,
    anchor_paths,
)
from hassette.exceptions import ConfigError
from hassette.types.enums import ForgottenAwaitBehavior
from hassette.types.types import FRAMEWORK_APP_KEY_PREFIX, AppDict, is_framework_key
from hassette.utils.app_utils import autodetect_apps, clean_app

LOGGER = getLogger(__name__)

TOKEN_SHORT_THRESHOLD = 8
TOKEN_MEDIUM_THRESHOLD = 12
TOKEN_SHORT_PREFIX_LENGTH = 3
TOKEN_LONG_PREFIX_LENGTH = 6

PYDANTIC_INSTANCE_STATE = ("__dict__", "__pydantic_fields_set__", "__pydantic_extra__", "__pydantic_private__")
"""Every attribute pydantic keeps a model instance's state in; `HassetteConfig.reload` swaps all of them."""


@dataclass(frozen=True)
class LoadInputs:
    """What a config was built from, replayed by `HassetteConfig.reload`."""

    environ: Mapping[str, str] = field(repr=False)
    """Kept out of repr: the snapshot holds every secret in the process environment."""
    cwd: Path
    config_file: FileList | None
    env_file: FileList | None
    strict_inputs: bool
    init_kwargs: dict[str, Any]
    """Setting values passed to `__init__`, with raw secrets swapped for their validated `SecretStr`."""


class HassetteConfig(ExcludeExtrasMixin, BaseSettings):
    """Configuration for Hassette."""

    model_config = SettingsConfigDict(
        env_prefix=SETTINGS_ENV_PREFIX,
        env_ignore_empty=True,
        extra="allow",
        env_nested_delimiter=ENV_NESTED_DELIMITER,
        coerce_numbers_to_str=True,
        validate_by_name=True,
        use_attribute_docstrings=True,
        validate_assignment=True,
        cli_parse_args=False,
        nested_model_default_partial_update=True,
    )

    # dup-ignore-start: pydantic-settings fixes the settings_customise_sources override signature
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type["BaseSettings"],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,  # noqa: ARG003 - pydantic-settings fixes the signature
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # dup-ignore-end
        build = ACTIVE_BUILD.get()
        if build is None:
            # sources resolve only inside BaseSettings.__init__, which HassetteConfig.__init__ wraps in a build
            raise RuntimeError("HassetteConfig settings sources resolved outside HassetteConfig.__init__")

        locations = build.locations
        init_kwargs = init_settings.init_kwargs if isinstance(init_settings, InitSettingsSource) else {}
        return (
            # the resolver owns config_dir: it decided which files are read
            InitSettingsSource(settings_cls, {"config_dir": locations.config_dir}),
            InitSettingsSource(settings_cls, anchor_paths(settings_cls, init_kwargs, build.cwd)),
            SnapshotEnvSettingsSource(settings_cls, build),
            # a later .env file wins, and an earlier source has priority
            *(FileDotEnvSettingsSource(settings_cls, path, build) for path in reversed(locations.env_files)),
            file_secret_settings,
            HassetteTomlConfigSettingsSource(settings_cls, locations.toml_files, build),
        )

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

    cli: CliConfig = Field(default_factory=CliConfig)
    """CLI client connect target, TLS, and credential settings."""

    timezone: str | None = Field(default=None)
    """IANA timezone name (e.g. ``"America/Chicago"``) used for all wall-clock
    operations: scheduler trigger resolution, event timestamp conversion, and
    state model datetime fields.

    When ``None`` (default), the system process timezone is used. Set this when
    the hassette process runs in a different timezone than Home Assistant (e.g.
    Docker containers running UTC while HA is configured for a local zone)."""

    dev_mode: bool = Field(default_factory=get_dev_mode)
    """Enable developer mode, which may include additional logging and features."""

    # Home Assistant connection — cross-cutting
    base_url: str = Field(default="http://127.0.0.1:8123", json_schema_extra={"ui": {"label": "Base URL"}})
    """Base URL of the Home Assistant instance"""

    verify_ssl: bool = Field(default=True, json_schema_extra={"ui": {"label": "Verify SSL"}})
    """Whether to verify SSL certificates when connecting to Home Assistant. Useful to disable for self-signed
    certificates."""

    rest_request_timeout_seconds: float = Field(default=30.0, gt=0, allow_inf_nan=False)
    """Default total timeout in seconds for outbound REST requests to Home Assistant, applied per retry attempt.
    Passed to aiohttp as a :class:`aiohttp.ClientTimeout`. Override per call by passing a ``timeout=`` kwarg to
    :meth:`~hassette.core.api_resource.ApiResource.rest_request`."""

    token: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("token", "hassette__token", "ha_token", "home_assistant_token"),
    )
    """Access token for Home Assistant instance.

    Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs
    and string representations.  Unwrap with ``token.get_secret_value()`` when
    the plaintext is required (e.g. HTTP auth headers, WebSocket auth payload).
    """

    # only used when constructed outside __init__: a build always supplies config_dir as an init source
    config_dir: Path = Field(default_factory=default_config_dir)
    """Directory ``hassette.toml`` and ``.env`` are read from, and the default home of ``apps.directory``.

    Set it with the ``HASSETTE__CONFIG_DIR`` environment variable or ``--config-dir``. It can't be set
    in ``hassette.toml`` or ``.env``, since those files are found through it, and an explicit one must
    exist. When unset, Hassette searches ``/config`` (if it exists) or the platform config directory,
    then the working directory, then ``./config``; an existing ``/config`` is then also the home of
    ``apps.directory``."""

    # reads the active ConfigBuild's environment (see hassette.config.build); the live env outside one
    data_dir: Path = Field(default_factory=default_build_data_dir)
    """Directory to store Hassette data: absolute, or relative to the config file that sets it."""

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

    only_apps: tuple[str, ...] = Field(default_factory=tuple)
    """App keys to run exclusively — every other configured app is excluded.

    Set by ``hassette run --app <key>`` (repeat the flag or pass a comma-separated list).
    Honored in both dev and production mode."""

    forgotten_await_behavior: ForgottenAwaitBehavior | None = Field(default=None)
    """Global default for forgotten-await detection behavior.

    When ``None`` (default), the effective behavior is ``"warn"``.  Per-app
    ``AppConfig.forgotten_await_behavior`` overrides this when set.  Set to ``"ignore"``
    to suppress warnings globally, or ``"error"`` to escalate via ``filterwarnings("error")``."""

    @property
    def locations(self) -> ConfigLocations:
        """The resolved config locations this config was built from."""
        return self._locations

    @property
    def env_files(self) -> set[Path]:
        """Return the existing ``.env`` files this config reads."""
        return filter_paths_to_unique_existing(list(self._locations.env_files))

    @property
    def toml_files(self) -> set[Path]:
        """Return the existing TOML files that are loaded, including ``*.local.toml`` overlays."""
        base_files = list(self._locations.toml_files)
        return filter_paths_to_unique_existing([*base_files, *local_overlay_paths(base_files)])

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
        """Create data_dir, and config_dir when it was defaulted, if they don't exist.

        An explicit config_dir that doesn't exist never gets here: construction rejects it.
        """
        for directory in (self.config_dir, self.data_dir):
            if not directory.exists():
                LOGGER.debug("Creating directory %s as it does not exist", directory)
                directory.mkdir(parents=True, exist_ok=True)

    _load_inputs: LoadInputs = PrivateAttr()
    _locations: ConfigLocations = PrivateAttr()

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        config_file: FileList | None = None,
        env_file: FileList | None = None,
        strict_inputs: bool = True,
        cwd: Path | None = None,
        **kwargs: Any,
    ) -> None:
        """Load the configuration from init kwargs, the environment, ``.env`` files and ``hassette.toml``.

        Args:
            environ: Process environment to read. Defaults to a snapshot of ``os.environ`` taken now;
                `reload` reuses the same snapshot, so variables loaded into ``os.environ`` later
                (``import_dot_env_files``) never shadow the ``.env`` files they came from.
            config_file: TOML file(s) to read instead of searching (``--config-file``). A subclass can
                pin its own with ``model_config["toml_file"]``; an empty list reads none.
            env_file: ``.env`` file(s) to read instead of searching (``--env-file``), pinned the same
                way with ``model_config["env_file"]``.
            strict_inputs: Reject explicit locations that don't exist, keys that match no setting, and
                ``config_dir`` set in a file. CLI client commands pass False so a typo doesn't stop
                ``hassette status``.
            cwd: Directory every relative input (location arguments, env and init-kwarg paths)
                resolves against. Defaults to the current directory now; `reload` reuses it.
            **kwargs: Setting values, the highest-priority source. A ``config_dir`` here is explicit.

                Note: relative ``str``/``Path`` values of path settings resolve against `cwd`, but a
                model instance (``apps=AppsConfig(directory=Path("rel"))``) is used as given, without
                anchoring.

        Raises:
            ConfigError: The configuration is invalid.
        """
        environ = dict(os.environ if environ is None else environ)
        cwd = (cwd or Path.cwd()).resolve()
        model_config = type(self).model_config
        locations = resolve_locations(
            environ,
            # read here to decide which files are searched; the field value itself then comes from
            # the build's first source (see settings_customise_sources), which outranks this kwarg
            config_dir=kwargs.get("config_dir"),
            config_file=config_file if config_file is not None else model_config.get("toml_file"),
            env_file=env_file if env_file is not None else model_config.get("env_file"),
            cwd=cwd,
        )
        # before construction, so a missing file is reported instead of the errors its absence causes
        if strict_inputs:
            check_explicit_locations(locations)
        build = ConfigBuild(environ, locations, cwd)
        try:
            with open_build(build):
                super().__init__(**kwargs)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

        if strict_inputs:
            check_config_dir_not_in_files(build)
            check_unknown_keys(type(self), build)

        # Swap raw secrets for their validated SecretStr so the plaintext isn't kept alive in a
        # second, unmasked place for the life of the config. SecretStr round-trips as an init kwarg.
        init_kwargs = dict(kwargs)
        for name in kwargs:
            if isinstance(validated := getattr(self, name, None), SecretStr):
                init_kwargs[name] = validated
        self._load_inputs = LoadInputs(
            environ=environ,
            cwd=cwd,
            config_file=config_file,
            env_file=env_file,
            strict_inputs=strict_inputs,
            init_kwargs=init_kwargs,
        )
        self._locations = locations

    def reload(self) -> None:
        """Reload the configuration from all sources, replacing this config only if the new one is valid.

        A candidate is built and its app manifests validated first; if either step raises, this
        config is untouched. Init kwargs are replayed because they are the highest-priority source:
        they carry the `hassette run` flags, and a file-watcher reload that dropped them would
        silently undo `--app` on the first save.

        Raises:
            ConfigError: The configuration on disk is invalid; the running config is unchanged.
        """
        inputs = self._load_inputs
        candidate = type(self)(
            environ=inputs.environ,
            cwd=inputs.cwd,
            config_file=inputs.config_file,
            env_file=inputs.env_file,
            strict_inputs=inputs.strict_inputs,
            **inputs.init_kwargs,
        )
        candidate.set_validated_app_manifests()
        # Become the candidate in place, so every holder of this config sees the reload. The private
        # state (_load_inputs, _locations) moves with it. object.__setattr__ bypasses validate_assignment.
        # Sub-model objects read from the old config (e.g. a saved `config.websocket`) keep the old values.
        for attr in PYDANTIC_INSTANCE_STATE:
            object.__setattr__(self, attr, getattr(candidate, attr))

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

    def require_token(self) -> None:
        """Raise `ConfigError` when no Home Assistant token is set; the server can't start without one."""
        if not self.token:
            raise ConfigError(
                "HA token is required for server startup. "
                "Set HASSETTE__TOKEN or HA_TOKEN in your environment or .env file."
            )

    def check_explicit_app_manifests(self) -> None:
        """Validate the app entries written in the config, without autodetect (which imports app modules).

        Raises:
            ConfigError: An entry has a reserved or unsafe key, or fails `AppManifest` validation.
        """
        validate_app_manifests(clean_explicit_apps(self.apps))

    def set_validated_app_manifests(self):
        """Cleans up and validates the apps configuration, including auto-detection."""
        cleaned_apps_dict = clean_explicit_apps(self.apps)

        # track known paths to simplify dupe detection during auto-detect
        known_paths: set[Path] = {v["full_path"] for v in cleaned_apps_dict.values()}

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

        app_manifest_dict = validate_app_manifests(cleaned_apps_dict)
        self.apps.manifests = app_manifest_dict

        warn_on_cache_key_collisions(app_manifest_dict)


def clean_explicit_apps(apps: AppsConfig) -> dict[str, AppDict]:
    """Return the app entries written in the config, cleaned; entries missing required keys are skipped."""
    cleaned: dict[str, AppDict] = {}
    for k, v in apps.apps.items():
        if not isinstance(v, dict):
            continue
        try:
            cleaned[k] = clean_app(k, v, apps.directory)
        except (KeyError, TypeError):
            LOGGER.warning("Skipping app %r: missing required keys (filename or class_name)", k)
    return cleaned


def validate_app_manifests(cleaned_apps: dict[str, AppDict]) -> dict[str, AppManifest]:
    """Validate cleaned app entries into manifests, rejecting reserved and unsafe app keys.

    Raises:
        ConfigError: An entry has a reserved or unsafe key, or fails `AppManifest` validation.
    """
    manifests: dict[str, AppManifest] = {}
    for k, v in cleaned_apps.items():
        if is_framework_key(k):
            raise ConfigError(
                f"App key {k!r} is reserved for framework internals "
                f"(reserved prefix: '{FRAMEWORK_APP_KEY_PREFIX}'). "
                f"Rename the app in your configuration (source: {v.get('full_path', 'unknown')})."
            )
        if reason := unsafe_app_key_reason(k):
            raise ConfigError(
                f"App key {k!r} {reason}; app keys are used as cache directory names. "
                f"Rename the app in your configuration (source: {v.get('full_path', 'unknown')})."
            )
        try:
            manifests[k] = AppManifest.model_validate(v)
        except ValidationError as exc:
            raise ConfigError(f"Invalid app {k!r}: {exc}") from exc
    return manifests


def unsafe_app_key_reason(app_key: str) -> str | None:
    r"""Return why *app_key* can't be used as a cache directory name, or None if it is safe.

    The default cache key is ``{app_key}/{index}``, so an app key must be a single path segment
    (no ``/`` or ``\``) and must also pass the same checks as an explicit ``cache_key``.
    """
    if "/" in app_key or "\\" in app_key:
        return "must not contain path separators ('/' or '\\')"
    return unsafe_cache_path_reason(app_key)


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

    Sharing a resolved cache_key across apps is usually a configuration mistake, so this surfaces
    it at config-load time rather than as silent cross-app cache contamination. Intentional sharing
    is opted into per app with ``cache_shared = true``. The warning is skipped only when every app
    sharing the key opts in; otherwise it names the apps missing the flag.
    """
    owners_by_resolved_key: dict[str, set[str]] = {}
    for app_key, manifest in manifests.items():
        for resolved_key in resolve_cache_keys(app_key, manifest):
            owners_by_resolved_key.setdefault(resolved_key, set()).add(app_key)

    for resolved_key, owners in owners_by_resolved_key.items():
        if len(owners) <= 1:
            continue
        not_opted_in = sorted(owner for owner in owners if not manifests[owner].cache_shared)
        if not not_opted_in:
            continue
        LOGGER.warning(
            "Multiple apps resolve to the same cache_key %r: %s. Apps without `cache_shared = true`: %s. "
            "If sharing is intentional, set `cache_shared = true` on every app sharing this key; otherwise "
            "set an explicit, unique `cache_key` on each app to avoid cache cross-contamination.",
            resolved_key,
            sorted(owners),
            not_opted_in,
        )


NESTED_GROUPS: dict[str, type] = {
    name: field.annotation
    for name, field in HassetteConfig.model_fields.items()
    if isinstance(field.annotation, type) and issubclass(field.annotation, ExcludeExtrasMixin)
}
