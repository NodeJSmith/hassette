"""Nested configuration model groups for HassetteConfig.

Each class groups a logical subset of configuration fields. All inherit
``ExcludeExtrasMixin`` and ``BaseModel`` (not ``BaseSettings``) so Pydantic
initialises them as sub-models, not independent settings roots.
"""

import os
from functools import partial
from logging import getLevelNamesMapping, getLogger
from pathlib import Path
from typing import Annotated, Any

from hassette_wire import LogLevel
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from hassette.config.build import default_apps_dir
from hassette.config.classes import AppManifest, ExcludeExtrasMixin
from hassette.config.helpers import coerce_log_level, log_level_default_factory
from hassette.logging_ import RESERVED_EXTRA_LOGGER_NAMES, LogFormat
from hassette.types.enums import BlockingIOBehavior
from hassette.types.types import RawAppDict
from hassette.utils.aiosqlite_utils import SQLITE_BUSY_TIMEOUT_MS

LOGGER = getLogger(__name__)
SHUTDOWN_TIMEOUT_SECONDS = 10
"""Default for ``LifecycleConfig.shutdown_timeout_seconds``: the bound on each shutdown hook."""

SESSION_FINALIZE_TIMEOUT_SECONDS = SQLITE_BUSY_TIMEOUT_MS / 1000
"""Fixed cap on writing the session's final record in the foundation shutdown stage."""

SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 5
"""Fixed cap on draining the database write queue in the foundation shutdown stage."""

SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS = 10.0
"""Fixed join-or-interrupt budget for sync-handler worker threads at shutdown (HA's
``EXECUTOR_SHUTDOWN_TIMEOUT``)."""

FOUNDATION_SHUTDOWN_BUDGET_SECONDS = (
    SESSION_FINALIZE_TIMEOUT_SECONDS + SHUTDOWN_DRAIN_TIMEOUT_SECONDS + SYNC_EXECUTOR_JOIN_TIMEOUT_SECONDS
)
"""Fixed budget of the foundation shutdown stage, the sum of its sequential steps' caps: the session
finalize, the write-queue drain, and the executor join. The stop stage gets
``total_shutdown_timeout_seconds`` minus this."""


LogLevelAnnotation = Annotated[LogLevel, BeforeValidator(partial(coerce_log_level, fallback="INFO"))]
APP_REQUIRED_KEYS = frozenset({"filename", "class_name"})
DEFAULT_WEB_API_PORT = 8126


def validate_positive_or_none(value: Any) -> float | None:
    """Validate that a timeout value is None or a positive number."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("timeout must be None or a positive number")
    val = float(value)
    if val <= 0:
        raise ValueError("timeout must be None or a positive number")
    return val


class DatabaseConfig(ExcludeExtrasMixin, BaseModel):
    """Database storage, retention, write-queue, and operational-interval settings."""

    path: Path | None = Field(default=None)
    """Path to the SQLite database file: absolute, or relative to the config file that sets it. Defaults to
    data_dir / "hassette.db" when None."""

    shutdown_snapshot_path: Path | None = Field(default=None)
    """Where to write a consistent single-file copy of the database on a clean shutdown: absolute, or relative
    to the config file that sets it. The copy is written to a ``.tmp`` sibling first and renamed into place, so
    the file is always complete. None (the default) writes no copy. The Home Assistant add-on sets it, so a
    backup taken while the add-on is stopped carries the database as of its last stop."""

    retention_days: int = Field(default=30, ge=1)
    """Number of days to retain app-tier execution records in the ``executions`` table.
    Framework-tier records use ``framework_retention_days`` instead."""

    framework_retention_days: int = Field(default=30, ge=1)
    """Number of days to retain framework-tier execution records. Must be <= retention_days."""

    max_size_mb: float = Field(default=500, ge=0)
    """Maximum live data in MB. The limit applies to in-use database pages, not the file on disk:
    free pages and the WAL don't count, so the file can sit above the limit by that amount until
    reclaim runs. When live data exceeds it, oldest execution and blocking-event records are
    deleted; log records are exempt and expire only on ``logging.log_retention_days``.
    0 disables the size failsafe."""

    migration_timeout_seconds: int = Field(default=120, ge=10)
    """Maximum seconds to wait for SQL schema migrations to complete at startup."""

    write_queue_max: int = Field(default=2000, ge=1)
    """Maximum pending coroutines in the DatabaseService write queue. Bounds memory growth
    under sustained I/O pressure. Fire-and-forget tasks are dropped on overflow; submit()
    callers block until space is available."""

    telemetry_write_queue_max: int = Field(default=1000, ge=1)
    """Maximum pending records in the CommandExecutor write queue before records are dropped."""

    heartbeat_interval_seconds: int = Field(default=300, ge=10)
    """Interval in seconds between database heartbeat checks."""

    retention_interval_seconds: int = Field(default=3600, ge=60)
    """Interval in seconds between retention enforcement runs."""

    size_failsafe_interval_seconds: int = Field(default=3600, ge=60)
    """Interval in seconds between size failsafe enforcement runs."""

    size_failsafe_max_iterations: int = Field(default=10, ge=1)
    """Maximum number of delete-batch iterations per size failsafe run."""

    size_failsafe_delete_batch: int = Field(default=1000, ge=1)
    """Number of rows deleted per batch during size failsafe enforcement."""

    retention_delete_batch: int = Field(default=1000, ge=1)
    """Number of rows deleted per batch during age-based retention cleanup. Each batch commits
    independently so no single transaction holds a lock across an entire target's delete."""

    retention_max_batches_per_target: int = Field(default=100, ge=1)
    """Maximum batches per retention target per cleanup invocation. Bounds worst-case occupancy
    of the write queue when a target has a large backlog; any remainder is picked up on the
    next retention cycle."""

    write_submit_timeout_seconds: float = Field(default=60.0, ge=0.1)
    """Maximum seconds an awaited database write may wait in the write queue before it starts
    executing. On expiry the write is withdrawn and the caller gets a TimeoutError, so a
    long-running retention or size-failsafe pass delays other writers instead of suspending
    them indefinitely. A write that has already started is not interrupted."""

    max_consecutive_heartbeat_failures: int = Field(default=3, ge=1)
    """Maximum consecutive heartbeat failures before the database service is considered unhealthy."""

    read_timeout_seconds: float = Field(default=10.0, ge=0.1)
    """Maximum seconds to wait for a telemetry read query before raising TimeoutError."""

    max_flush_interval_seconds: float = Field(default=5.0, ge=0.1)
    """Maximum seconds a record may sit in the CommandExecutor write queue before a
    time-based flush is forced, even if the batch size threshold has not been reached."""

    framework_record_errors: bool = Field(default=True)
    """Always persist framework-tier executions with any non-success status. When False,
    framework errors are subject to the same sampling as routine successes — almost never
    desirable."""

    framework_record_slow_ms: float | None = Field(default=100.0, ge=0)
    """Persist framework-tier executions whose duration exceeds this threshold (ms),
    regardless of status. None disables duration-based persistence."""

    framework_record_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    """Fraction of routine (successful, fast) framework-tier executions to persist.
    0.0 drops all routine framework executions; 1.0 persists all (no filtering).
    Values between 0 and 1 sample randomly at the given rate."""

    @model_validator(mode="after")
    def validate_framework_retention_days(self) -> "DatabaseConfig":
        """Ensure framework_retention_days stays within the standard retention window."""
        if self.framework_retention_days > self.retention_days:
            raise ValueError(
                f"framework_retention_days ({self.framework_retention_days}) must be <= "
                f"retention_days ({self.retention_days})"
            )
        return self


class WebSocketConfig(ExcludeExtrasMixin, BaseModel):
    """WebSocket connection and timeout settings.

    Reconnect pacing is fixed, not configurable: see ``hassette.core.websocket_reconnect``. The
    authentication, response, total and cleanup timeouts are module constants in
    ``hassette.core.websocket_service`` and ``hassette.core.websocket_io``.
    """

    connection_timeout_seconds: int = Field(default=5)
    """Length of time to wait for WebSocket connection to complete. Passed to aiohttp."""

    heartbeat_interval_seconds: int = Field(default=30)
    """Interval to send ping messages to keep the WebSocket connection alive. Passed to aiohttp."""


class LoggingConfig(ExcludeExtrasMixin, BaseModel):
    """Logging level, format, queue, persistence, and per-service log-level settings."""

    log_level: LogLevelAnnotation = Field(default="INFO")
    """Logging level for Hassette."""

    log_format: LogFormat = Field(default="auto")
    """Console output format. ``"auto"`` detects TTY vs pipe automatically. ``"console"`` forces
    colored human-readable output. ``"compact"`` is the console format with a time-only timestamp and
    no level padding, for narrow viewers such as the add-on's Log tab; ``"auto"`` never picks it.
    ``"json"`` forces one-JSON-object-per-line output."""

    log_queue_max: int = Field(default=2000, ge=1)
    """Maximum size of the inter-thread log queue. Records are dropped when the queue is full."""

    log_persistence_level: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Minimum log level for database persistence. Records below this level are not stored. Defaults to log_level.

    May not be stricter than ``log_level`` (a validation error otherwise): the web UI's log view reads
    exclusively from persisted records, so a stricter floor would make records visible in the live log
    stream unqueryable through the UI. Lower it (e.g. to ``"DEBUG"``) to persist records you don't
    otherwise log at the global level, such as a per-service override logging at ``"DEBUG"``."""

    log_retention_days: int = Field(default=30, ge=1)
    """Number of days to retain persisted log records. Must be <= database.retention_days."""

    database_service: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the database service. Defaults to log_level."""

    bus_service: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the event bus service. Defaults to log_level."""

    scheduler_service: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the scheduler service. Defaults to log_level."""

    app_handler: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the app handler service. Defaults to log_level."""

    web_api: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the web API service. Defaults to log_level."""

    websocket: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the WebSocket service. Defaults to log_level."""

    service_watcher: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the service watcher. Defaults to log_level."""

    file_watcher: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the file watcher service. Defaults to log_level."""

    task_bucket: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for task buckets. Defaults to log_level."""

    command_executor: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the command executor service. Defaults to log_level."""

    apps: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Default logging level for apps, can be overridden in app initialization. Defaults to log_level."""

    state_proxy: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the state proxy resource. Defaults to log_level."""

    api: LogLevelAnnotation = Field(default_factory=log_level_default_factory)
    """Logging level for the API resource (REST/WebSocket client). Defaults to log_level."""

    extra_loggers: tuple[Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")], ...] = Field(
        default_factory=tuple
    )
    """Additional logger names (outside the ``hassette.`` tree) to attach to Hassette's own
    logging pipeline — same handlers, formatter, and level as the ``hassette`` logger. Use this
    to opt an app author's own package logger (e.g. ``logging.getLogger("my_app.notify")``) into
    structured console output, WebSocket log capture, and DB persistence, without renaming it
    into the ``hassette.`` namespace.

    Each named logger is reset the same way the ``hassette`` logger is: existing handlers and
    filters on it are cleared before Hassette's own handler is attached. If you configure a
    third-party logger that already has its own handler (e.g. a library-installed
    ``FileHandler``), that handler is removed.

    An empty or whitespace-only name is rejected — ``logging.getLogger("")`` returns the root
    logger, not a no-op, and (e.g. from a stray comma in a TOML array) would silently reroute
    the root logger through Hassette's pipeline, double-logging every propagating logger in the
    process. ``"root"`` is rejected for the identical reason — ``logging.getLogger("root")`` is
    stdlib's special case for that same root logger object, not a distinctly-named one.
    ``"hassette"`` and ``"py.warnings"`` are also rejected: both are already managed outright by
    Hassette's own logging setup, and reconfiguring them here would silently override wiring the
    framework depends on (see ``reject_reserved_logger_name`` below)."""

    @field_validator("extra_loggers")
    @classmethod
    def reject_reserved_logger_name(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject a name that either aliases the root logger or that Hassette already manages.

        ``"root"`` (``hassette.logging_.RESERVED_EXTRA_LOGGER_NAMES``) resolves to the same
        object as the process's root logger — the same stdlib special case that makes an empty
        string do this too (see the field docstring above) — so adopting it would clear the root
        logger's handlers and route every propagating logger through Hassette's pipeline, not
        just reconfigure one named logger.

        ``"hassette"`` and ``"py.warnings"`` are reset and wired by
        ``enable_basic_logging()``/``LoggingService`` regardless of this setting. ``py.warnings``
        in particular is fixed at ``WARNING`` independent of ``log_level`` so that
        ``HassetteForgottenAwaitWarning`` capture can't be silently disabled by raising
        ``log_level`` — letting it back in through ``extra_loggers`` would reintroduce exactly
        that footgun.
        """
        reserved = RESERVED_EXTRA_LOGGER_NAMES.intersection(value)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(
                f'extra_loggers may not contain {names} — reserved ("root" aliases the process\'s '
                'root logger; "hassette"/"py.warnings" are already managed by Hassette\'s own logging setup)'
            )
        return value

    @model_validator(mode="after")
    def reject_persistence_stricter_than_log_level(self) -> "LoggingConfig":
        """Reject a ``log_persistence_level`` above ``log_level`` (see the field docstring for why)."""
        levels = getLevelNamesMapping()
        if levels[self.log_persistence_level] > levels[self.log_level]:
            raise ValueError(
                f"log_persistence_level ({self.log_persistence_level}) may not be stricter than "
                f"log_level ({self.log_level}): records shown in the live log would be missing from the "
                "web UI's log view. Lower log_persistence_level or raise log_level."
            )
        return self

    all_hass_events: bool = Field(default=False)
    """Whether to include all Home Assistant events in bus debug logging. Should be used sparingly."""

    all_hassette_events: bool = Field(default=False)
    """Whether to include all Hassette events in bus debug logging, including topics apps publish with
    ``Bus.emit``. Should be used sparingly."""


class LifecycleConfig(ExcludeExtrasMixin, BaseModel):
    """Startup, shutdown, and per-operation timeout settings for the resource lifecycle."""

    startup_timeout_seconds: int = Field(default=30)
    """Length of time to wait for each wave of Hassette resources to start before giving up.
    Must be >= app_startup_timeout_seconds since AppHandler readiness waits for app bootstrap."""

    app_startup_timeout_seconds: int = Field(default=20)
    """Length of time to wait for an app to start before giving up."""

    shutdown_timeout_seconds: float = Field(default=SHUTDOWN_TIMEOUT_SECONDS, gt=0)
    """Length of time each shutdown hook (an app's or a framework resource's ``on_shutdown`` and the hooks
    around it) may run before it is cancelled. A hook gets less when its stage has less time left."""

    failed_instance_cleanup_timeout_seconds: int = Field(default=5)
    """Seconds to wait for listener/job cleanup after an app instance fails to initialize or its stop times out."""

    total_shutdown_timeout_seconds: float = Field(default=45, gt=FOUNDATION_SHUTDOWN_BUDGET_SECONDS)
    """Maximum wall-clock seconds for the whole Hassette shutdown. The foundation stage (database and
    worker threads) keeps a fixed budget; everything else stops within the rest, and so does each runtime
    app stop or reload. Your supervisor's stop grace period must exceed this."""

    sync_executor_max_workers: int = Field(default_factory=lambda: min(32, (os.cpu_count() or 1) + 4), ge=1)
    """Pool ceiling for the dedicated sync-handler thread pool executor.
    Sized to match the prior implicit default-pool ceiling (min(32, cpu+4)). This is a
    reasonable starting ceiling, NOT a literal behavior-equivalence guarantee: the old
    shared pool also served logging and DB work, so a same-size dedicated pool gives sync
    handlers more effective headroom in practice."""

    sync_executor_saturation_warn_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    """Fraction of the sync-handler thread pool that must be occupied before Hassette logs a
    pool-saturation WARNING. Independent from command_executor_capacity_warn_threshold — the two
    govern different subsystems (thread-pool occupancy vs. per-entity write-queue depth) and may
    be tuned separately."""

    sync_executor_saturation_warn_rate_limit_seconds: float = Field(default=30.0, gt=0)
    """Minimum seconds between repeated pool-saturation WARNINGs. Raising this above the internal
    30s probe cadence delays, but does not eliminate, probe-triggered warnings during sustained
    pool starvation."""

    command_executor_capacity_warn_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    """Fraction of the telemetry write-queue capacity that must be filled before Hassette logs a
    queue-capacity WARNING. Independent from sync_executor_saturation_warn_threshold — see there
    for why the two are not shared."""

    command_executor_capacity_warn_rate_limit_seconds: float = Field(default=30.0, gt=0)
    """Minimum seconds between repeated queue-capacity WARNINGs."""

    event_handler_timeout_seconds: float | None = Field(default=600.0)
    """Default timeout in seconds for event handler execution. ``None`` disables the default timeout.
    Individual listeners can override via ``timeout=`` or ``timeout_disabled=True``."""

    max_concurrent_dispatches: int = Field(default=50, ge=1)
    """Ceiling on concurrent event-handler invocations dispatched by the bus.

    The bus fans an event out to one task per matching listener. Without a bound, a state
    storm hitting many listeners spawns unbounded tasks and can exhaust memory and the event
    loop. When this many handlers are already in flight, the bus waits for a slot before
    spawning more — that wait propagates back through the inbound event channel to the
    Home Assistant WebSocket reader (true backpressure).

    A running handler holds its slot until it returns or hits ``event_handler_timeout_seconds``,
    so a slow handler can stall dispatch up to that timeout. Read once at startup; changing it
    requires a restart."""

    error_handler_timeout_seconds: float | None = Field(default=5.0)
    """Default timeout in seconds for error handler execution. ``None`` disables the default timeout."""

    run_sync_timeout_seconds: int | float = Field(default=6)
    """Default timeout for synchronous function calls."""

    task_cancellation_timeout_seconds: int | float = Field(default=5)
    """Length of time to wait for tasks to cancel before forcing."""

    @field_validator("event_handler_timeout_seconds", "error_handler_timeout_seconds", mode="before")
    @classmethod
    def validate_timeouts(cls, value: Any) -> float | None:
        """Coerce the timeout to a float, rejecting values that are not None or positive."""
        return validate_positive_or_none(value)


class WebApiConfig(ExcludeExtrasMixin, BaseModel):
    """Web API and UI server host, port, buffer, and feature-flag settings."""

    # A group label (section title) must live on the model's own `model_config`, NOT on the
    # `Field(json_schema_extra=...)` of the group in HassetteConfig: a nested-model field is
    # emitted as a `$ref`, and the server-side deref (`jsonref.replace_refs`) drops `$ref`
    # sibling keys, so a `ui` block placed there is silently lost. Scalar field labels are not
    # `$ref` nodes and so use `Field(json_schema_extra=...)` as usual.
    model_config = ConfigDict(json_schema_extra={"ui": {"group_label": "Web API"}})

    run: bool = Field(default=True)
    """Whether to run the web API service (includes healthcheck and UI backend)."""

    run_ui: bool = Field(default=True, json_schema_extra={"ui": {"label": "Run UI"}})
    """Whether to serve the web UI dashboard. Only used when run is True."""

    ui_hot_reload: bool = Field(default=False, json_schema_extra={"ui": {"label": "UI Hot Reload"}})
    """Watch web UI static files and templates for changes and push live reloads to the browser."""

    host: str = Field(default="0.0.0.0")
    """Host to bind the web API server to."""

    port: int = Field(default=DEFAULT_WEB_API_PORT)
    """Port to run the web API server on."""

    cors_origins: tuple[str, ...] = Field(
        default=("http://localhost:3000", "http://localhost:5173"),
        json_schema_extra={"ui": {"label": "CORS Origins"}},
    )
    """Allowed CORS origins for the web API, typically the UI dev server."""

    auth_enabled: bool = Field(default=True, json_schema_extra={"ui": {"label": "Auth Enabled"}})
    """Whether the web API requires a credential before serving any ``/api/*`` route.

    A valid ``Authorization: Bearer <token>`` header, a valid session cookie, or a request whose
    peer matches ``trusted_proxies`` all satisfy this check. ``GET /api/health/live``,
    ``GET /api/health/ready``, and ``POST /api/auth/session`` are always reachable regardless of
    this setting. Defaults to ``True`` so a fresh install is protected with zero configuration.

    Disabling this requires ``host`` to be a loopback address — Hassette refuses to start with
    ``auth_enabled=False`` on a non-loopback ``host``, since that combination would serve an
    unauthenticated API to any network peer that can reach the port."""

    auth_token: SecretStr | None = Field(default=None, json_schema_extra={"ui": {"label": "Auth Token"}})
    """Bearer token / session-cookie credential for the web API.

    Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs, string
    representations, and the ``GET /api/config`` response. Unwrap with
    ``auth_token.get_secret_value()`` only at the point of use (comparing the ``Authorization``
    header, minting a session cookie).

    When ``None`` at startup, ``WebApiService`` resolves one in this order: an existing token file
    at ``token_file``, or a freshly generated ``secrets.token_urlsafe(32)`` value written there.
    This field carries either an explicit operator-configured value or the value resolved during
    startup — it is not itself responsible for token generation."""

    token_file: Path | None = Field(default=None, json_schema_extra={"ui": {"label": "Token File"}})
    """Where the server reads and persists its own generated token: absolute, or relative to the
    config file that sets it. Defaults to ``<data_dir>/.web_api_token``.

    Ignored when ``auth_token`` is configured, which wins over the file; Hassette logs a warning
    when both are set. Not to be confused with ``cli.token_file``, the credential the CLI *sends*
    to a target."""

    trusted_proxies: tuple[str, ...] = Field(default=(), json_schema_extra={"ui": {"label": "Trusted Proxies"}})
    """Peer addresses that need no credential of their own.

    Each entry is an IP, CIDR, or hostname compared against the raw ASGI ``scope["client"]`` peer
    address — never ``X-Forwarded-For`` or any other client-suppliable header. Intended for a
    forward-auth gateway sitting in front of Hassette (a Home Assistant add-on's ingress, or a
    self-managed reverse proxy with its own login) so that gateway's own authentication can stand
    in for Hassette's. Hostname entries are resolved via DNS at startup and re-resolved
    periodically. A hostname that doesn't resolve yet (a Compose sibling that hasn't started)
    doesn't block startup: it trusts no peer until a later refresh resolves it. A malformed entry
    or one matching the entire address space (``0.0.0.0/0``, ``::/0``) fails startup. Entry parsing
    and matching are implemented separately from this field declaration.

    A matching peer skips the bearer-token/session-cookie check only for requests that send no
    ``Authorization`` header. A request carrying that header is validated against ``auth_token``
    regardless of its peer, and a wrong or malformed header is rejected rather than falling back to
    this list — so one host can serve gateway-authenticated browsers and token-authenticated API
    clients at the same time."""

    session_ttl: int = Field(default=3600, gt=0, json_schema_extra={"ui": {"label": "Session TTL (seconds)"}})
    """Maximum lifetime, in seconds, of a single session cookie *value* — not of a working session.

    A cookie whose remaining lifetime has fallen below half of this TTL is replaced with a
    freshly minted cookie on the next request it authenticates (sliding renewal), so an actively
    used dashboard is never interrupted mid-session. This is the only revocation lever in the
    design: a leaked cookie stops working within ``session_ttl`` seconds of the moment it was
    minted, without requiring the operator to rotate ``auth_token`` (which would invalidate every
    session and script at once)."""

    @field_validator("cors_origins")
    @classmethod
    def reject_wildcard_cors_origin(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Reject a wildcard CORS origin.

        ``CORSMiddleware`` is registered with ``allow_credentials=True`` as a hardcoded argument
        (``web/app.py``), not a configurable field. Combined with ``cors_origins=("*",)``, that
        would let any site make credentialed requests against the web API. This validator closes
        that misconfiguration at config load rather than leaving Starlette to reject it at
        request time with a confusing error.
        """
        if "*" in value:
            raise ValueError(
                'cors_origins may not contain "*" — combined with allow_credentials=True '
                "(hardcoded in web/app.py), a wildcard origin would allow any site to make "
                "credentialed requests against the web API."
            )
        return value


class AppsConfig(ExcludeExtrasMixin, BaseModel):
    """App directory, unconfigured-app warning, manifest, and raw-app-dict settings.

    In TOML, app definitions live alongside these settings under ``[hassette.apps]``:

    .. code-block:: toml

        [hassette.apps]
        directory = "apps"

        [hassette.apps.my_app]
        filename = "my_app.py"
        class_name = "MyApp"

    The ``model_validator`` separates known config fields from app-definition
    dicts so both coexist in the same TOML section.
    """

    warn_unconfigured: bool = Field(default=True)
    """Whether startup warns about each ``App``/``AppSync`` subclass in the app directory that no app entry
    configures. The scan parses files without importing them and skips virtualenv, cache, version-control,
    and vendored-package directories."""

    manifests: dict[str, AppManifest] = Field(default_factory=dict)
    """Validated app manifests, keyed by app name."""

    apps: dict[str, RawAppDict] = Field(default_factory=dict)
    """Raw configuration for Hassette apps, keyed by app name."""

    # <config home>/apps during a config build (see hassette.config.build), else ./apps
    directory: Path = Field(default_factory=default_apps_dir)
    """Directory to load user apps from: absolute, or relative to the config file that sets it. Defaults to
    ``apps`` in the config home: ``config_dir`` when it is set explicitly, else ``/config`` if it exists, else
    the working directory."""

    @model_validator(mode="before")
    @classmethod
    def extract_app_definitions(cls, data: Any) -> Any:
        """Separate app-definition dicts from known config fields."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        known = set(cls.model_fields)
        reserved = known - {"apps", "manifests"}
        app_defs: dict[str, Any] = {}
        for key in list(data):
            if key in known:
                if isinstance(data[key], dict) and key in reserved:
                    raise ValueError(
                        f"App name {key!r} conflicts with a reserved config field. "
                        f"Reserved names: {sorted(reserved)}. "
                        f"Rename the app in your configuration."
                    )
                continue
            if isinstance(data[key], dict):
                app_defs[key] = data.pop(key)
        if app_defs:
            existing = data.get("apps")
            if isinstance(existing, dict):
                data["apps"] = {**existing, **app_defs}
            else:
                data["apps"] = app_defs
        return data

    @field_validator("apps", mode="before")
    @classmethod
    def remove_incomplete_apps(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Remove any apps that are missing required fields before validation."""
        missing_required = {k: v for k, v in value.items() if isinstance(v, dict) and not APP_REQUIRED_KEYS.issubset(v)}
        if missing_required:
            LOGGER.warning(
                "The following apps are missing required keys (%s) and will be ignored: %s",
                ", ".join(APP_REQUIRED_KEYS),
                list(missing_required.keys()),
            )
            for k in missing_required:
                value.pop(k)
        return value


class SchedulerConfig(ExcludeExtrasMixin, BaseModel):
    """Scheduler threshold and job-timeout settings."""

    behind_schedule_threshold_seconds: int | float = Field(default=5)
    """Threshold in seconds before a 'behind schedule' warning is logged for a job."""

    job_timeout_seconds: float | None = Field(default=600.0)
    """Default timeout in seconds for scheduled job execution. ``None`` disables the default timeout.
    Individual jobs can override via ``timeout=`` or ``timeout_disabled=True``."""

    @field_validator("job_timeout_seconds", mode="before")
    @classmethod
    def validate_timeouts(cls, value: Any) -> float | None:
        """Coerce the timeout to a float, rejecting values that are not None or positive."""
        return validate_positive_or_none(value)


class FileWatcherConfig(ExcludeExtrasMixin, BaseModel):
    """File watcher debounce, step, and enable/disable settings."""

    debounce_milliseconds: int = Field(default=3000)
    """Debounce time for file watcher events in milliseconds."""

    step_milliseconds: int = Field(default=500)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""


class BlockingIODetectionConfig(ExcludeExtrasMixin, BaseModel):
    """Blocking-call detection settings for the shared event loop.

    Controls the two-tier detection system: Tier 1 (always-on responsiveness watchdog, which
    catches any loop stall, including CPU-bound work) and Tier 2 (call-site interception of
    known blocking I/O primitives, dev-default / prod-opt-in).
    """

    # Group label on the model's own config — see WebApiConfig above for why this can't go on
    # the field reference in HassetteConfig (deref drops `$ref` sibling keys).
    model_config = ConfigDict(json_schema_extra={"ui": {"group_label": "Blocking Calls"}})

    behavior: BlockingIOBehavior | None = Field(default=None)
    """Global default behavior for blocking-call detection.

    When ``None`` (default), the effective behavior is ``"warn"``. Per-app
    ``AppConfig.blocking_io_behavior`` overrides this when set. Set to ``"ignore"`` to
    suppress detection globally, or ``"error"`` to escalate via ``filterwarnings("error")``."""

    watchdog_enabled: bool = Field(default=True)
    """Whether to run the Tier 1 loop-responsiveness watchdog. Defaults to True."""

    lag_threshold_seconds: float = Field(default=0.1, gt=0)
    """Tier 1: minimum loop lag in seconds before a blocking-detected event is emitted.
    Defaults to 100ms — brief stalls under this threshold are not reported."""

    min_events: int = Field(default=2, ge=1)
    """Tier 1: minimum number of lag events at one call site before it is reported as a finding.
    Defaults to 2 — a single stray stall is evidence, not proof, so it stays hidden until it
    recurs. Set to 1 to report every stall. Tier 2 findings are exact and are never gated."""

    watchdog_interval_seconds: float = Field(default=0.25, gt=0)
    """Tier 1: interval in seconds between watchdog heartbeat checks.
    Defaults to 250ms — trades detection latency for overhead."""

    capture_stack_on_block: bool = Field(default=True)
    """Whether to capture a stack snapshot of the loop thread when a severe stall is detected.
    Defaults to True. Set to False to reduce overhead on low-memory systems."""

    deep_detection_enabled: bool | None = Field(default=None)
    """Whether to enable Tier 2 call-site interception (monkeypatching of blocking primitives).

    When ``None`` (default), follows ``dev_mode``: enabled in dev, disabled in production unless
    ``allow_deep_detection_in_prod`` is set. Set explicitly to ``True`` or ``False`` to override
    the dev_mode default."""

    allow_deep_detection_in_prod: bool = Field(default=False)
    """Whether to enable Tier 2 deep detection in production mode.

    When True, Tier 2 call-site interception is active even when ``dev_mode`` is False, without
    also setting ``deep_detection_enabled``. An explicit ``deep_detection_enabled=False`` still
    disables Tier 2. Mirrors ``allow_reload_in_prod`` semantics. Defaults to False."""


class CliConfig(ExcludeExtrasMixin, BaseModel):
    """CLI client connect target, TLS, and credential settings."""

    # Group label on the model's own config — see WebApiConfig above for why this can't go on
    # the field reference in HassetteConfig (deref drops `$ref` sibling keys).
    model_config = ConfigDict(json_schema_extra={"ui": {"group_label": "CLI"}})

    server_url: str | None = Field(default=None, json_schema_extra={"ui": {"label": "Server URL"}})
    """Full base URL (scheme, host, port, and optional path prefix) of the Hassette instance the
    CLI connects to. When unset, the CLI derives its target from ``web_api.host``/``web_api.port``."""

    verify_ssl: bool = Field(default=True, json_schema_extra={"ui": {"label": "Verify SSL"}})
    """Whether to verify TLS certificates when connecting to a ``https://`` server_url. Disable for
    a self-signed deployment."""

    token_file: Path | None = Field(default=None, json_schema_extra={"ui": {"label": "Token File"}})
    """Path to a file containing the bearer credential for the target Hassette instance (absolute, or
    relative to the config file that sets it). Applies to any target, unlike the server-scoped,
    loopback-only ``web_api.token_file`` fallback (the server's own token location, not a credential
    you supply)."""

    auth_token: SecretStr | None = Field(default=None, json_schema_extra={"ui": {"label": "Auth Token"}})
    """Bearer credential for the target Hassette instance.

    Stored as a :class:`~pydantic.SecretStr` so the value is masked in logs, string
    representations, and the ``GET /api/config`` response. Unwrap with
    ``auth_token.get_secret_value()`` only at the point of use. Applies to any target, unlike
    ``web_api.auth_token`` which is scoped to the local instance only."""
