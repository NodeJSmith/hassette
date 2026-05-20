"""Nested configuration model groups for HassetteConfig.

Each class groups a logical subset of configuration fields. All inherit
``ExcludeExtrasMixin`` and ``BaseModel`` (not ``BaseSettings``) so Pydantic
initialises them as sub-models, not independent settings roots.
"""

from functools import partial
from logging import getLogger
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, field_validator, model_validator

from hassette.config.classes import AppManifest, ExcludeExtrasMixin
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.config.helpers import coerce_log_level, log_level_default_factory
from hassette.types.types import LOG_LEVEL_TYPE, RawAppDict

LOGGER = getLogger(__name__)

LOG_ANNOTATION = Annotated[LOG_LEVEL_TYPE, BeforeValidator(partial(coerce_log_level, fallback="INFO"))]


class DatabaseConfig(ExcludeExtrasMixin, BaseModel):
    """Database storage, retention, write-queue, and operational-interval settings."""

    path: Path | None = Field(default=None)
    """Path to the SQLite database file. Defaults to data_dir / "hassette.db" when None."""

    retention_days: int = Field(default=7, ge=1)
    """Number of days to retain execution records (handler_invocations, job_executions)."""

    max_size_mb: float = Field(default=500, ge=0)
    """Maximum database file size in MB. When exceeded, oldest execution records are deleted.
    0 disables the size failsafe."""

    migration_timeout_seconds: int = Field(default=120, ge=10)
    """Maximum seconds to wait for Alembic migrations to complete at startup."""

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

    size_failsafe_vacuum_pages: int = Field(default=100, ge=1)
    """Number of pages to vacuum per size failsafe run."""

    max_consecutive_heartbeat_failures: int = Field(default=3, ge=1)
    """Maximum consecutive heartbeat failures before the database service is considered unhealthy."""


class WebSocketConfig(ExcludeExtrasMixin, BaseModel):
    """WebSocket connection, retry, and recovery timing settings."""

    authentication_timeout_seconds: int = Field(default=10)
    """Length of time to wait for WebSocket authentication to complete."""

    response_timeout_seconds: int = Field(default=15)
    """Length of time to wait for a response from the WebSocket."""

    connection_timeout_seconds: int = Field(default=5)
    """Length of time to wait for WebSocket connection to complete. Passed to aiohttp."""

    total_timeout_seconds: int = Field(default=30)
    """Total length of time to wait for WebSocket operations to complete. Passed to aiohttp."""

    heartbeat_interval_seconds: int = Field(default=30)
    """Interval to send ping messages to keep the WebSocket connection alive. Passed to aiohttp."""

    connect_retry_max_attempts: int = Field(default=5)
    """Maximum number of attempts to establish the initial WebSocket connection before giving up."""

    connect_retry_initial_wait_seconds: float = Field(default=1.0)
    """Initial backoff wait in seconds between WebSocket connection retry attempts."""

    connect_retry_max_wait_seconds: float = Field(default=32.0)
    """Maximum backoff wait in seconds between WebSocket connection retry attempts."""

    early_drop_stable_window_seconds: float = Field(default=30.0)
    """Seconds a connection must stay alive before it is considered stable (resets early-drop counter)."""

    early_drop_max_retries: int = Field(default=5)
    """Maximum number of early-drop reconnect attempts before treating the failure as fatal."""

    early_drop_backoff_initial_seconds: float = Field(default=2.0)
    """Initial backoff wait in seconds between early-drop reconnect attempts."""

    early_drop_backoff_max_seconds: float = Field(default=60.0)
    """Maximum backoff wait in seconds between early-drop reconnect attempts."""

    max_recovery_seconds: float = Field(default=300.0)
    """Maximum total wall-clock seconds to spend on all WebSocket recovery attempts before giving up."""


class LoggingConfig(ExcludeExtrasMixin, BaseModel):
    """Logging level, format, queue, persistence, and per-service log-level settings."""

    log_level: LOG_ANNOTATION = Field(default="INFO")
    """Logging level for Hassette."""

    log_format: Literal["auto", "console", "json"] = Field(default="auto")
    """Console output format. ``"auto"`` detects TTY vs pipe automatically. ``"console"`` forces
    colored human-readable output. ``"json"`` forces one-JSON-object-per-line output."""

    log_queue_max: int = Field(default=2000, ge=1)
    """Maximum size of the inter-thread log queue. Records are dropped when the queue is full."""

    log_persistence_level: LOG_ANNOTATION = Field(default="INFO")
    """Minimum log level for database persistence. Records below this level are not stored."""

    log_retention_days: int = Field(default=3, ge=1)
    """Number of days to retain persisted log records. Must be <= database.retention_days."""

    database_service: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the database service. Defaults to log_level."""

    bus_service: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the event bus service. Defaults to log_level."""

    scheduler_service: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the scheduler service. Defaults to log_level."""

    app_handler: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the app handler service. Defaults to log_level."""

    web_api: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the web API service. Defaults to log_level."""

    websocket: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the WebSocket service. Defaults to log_level."""

    service_watcher: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the service watcher. Defaults to log_level."""

    file_watcher: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the file watcher service. Defaults to log_level."""

    task_bucket: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for task buckets. Defaults to log_level."""

    command_executor: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the command executor service. Defaults to log_level."""

    apps: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Default logging level for apps, can be overridden in app initialization. Defaults to log_level."""

    state_proxy: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the state proxy resource. Defaults to log_level."""

    api: LOG_ANNOTATION = Field(default_factory=log_level_default_factory)
    """Logging level for the API resource (REST/WebSocket client). Defaults to log_level."""

    all_events: bool = Field(default=False)
    """Whether to include all events in bus debug logging. Should be used sparingly."""

    all_hass_events: bool | None = Field(default=None)
    """Whether to include all Home Assistant events in bus debug logging.
    Defaults to False or the value of all_events."""

    all_hassette_events: bool | None = Field(default=None)
    """Whether to include all Hassette events in bus debug logging.
    Defaults to False or the value of all_events."""

    @model_validator(mode="after")
    def fill_event_defaults(self) -> "LoggingConfig":
        """Fill all_hass/hassette_events from all_events when not explicitly set."""
        if self.all_hass_events is None:
            self.all_hass_events = self.all_events
        if self.all_hassette_events is None:
            self.all_hassette_events = self.all_events
        return self


class LifecycleConfig(ExcludeExtrasMixin, BaseModel):
    """Startup, shutdown, and per-operation timeout settings for the resource lifecycle."""

    startup_timeout_seconds: int = Field(default=30)
    """Length of time to wait for each wave of Hassette resources to start before giving up.
    Must be >= app_startup_timeout_seconds since AppHandler readiness waits for app bootstrap."""

    app_startup_timeout_seconds: int = Field(default=20)
    """Length of time to wait for an app to start before giving up."""

    app_shutdown_timeout_seconds: int = Field(default=10)
    """Length of time to wait for an app to shut down before giving up."""

    resource_shutdown_timeout_seconds: int = Field(
        default_factory=lambda data: data.get("app_shutdown_timeout_seconds", 10)
    )
    """Per-phase timeout for resource shutdown. Defaults to app_shutdown_timeout_seconds."""

    total_shutdown_timeout_seconds: int = Field(default=30)
    """Maximum wall-clock seconds for the entire Hassette shutdown (hooks + propagation)."""

    registration_await_timeout: int = Field(default=30)
    """Timeout in seconds to wait for all pending listener/job DB registrations to flush
    before post-ready reconciliation. Prevents indefinite hangs if the DB write queue stalls."""

    event_handler_timeout_seconds: float | None = Field(default=600.0)
    """Default timeout in seconds for event handler execution. ``None`` disables the default timeout.
    Individual listeners can override via ``timeout=`` or ``timeout_disabled=True``."""

    error_handler_timeout_seconds: float | None = Field(default=5.0)
    """Default timeout in seconds for error handler execution. ``None`` disables the default timeout."""

    run_sync_timeout_seconds: int | float = Field(default=6)
    """Default timeout for synchronous function calls."""

    task_cancellation_timeout_seconds: int | float = Field(default=5)
    """Length of time to wait for tasks to cancel before forcing."""

    @field_validator("event_handler_timeout_seconds", "error_handler_timeout_seconds", mode="before")
    @classmethod
    def validate_timeouts(cls, value: Any) -> float | None:
        """Validate that timeout fields are None or a positive number."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("timeout must be None or a positive number")
        val = float(value)
        if val <= 0:
            raise ValueError("timeout must be None or a positive number")
        return val


class WebApiConfig(ExcludeExtrasMixin, BaseModel):
    """Web API and UI server host, port, buffer, and feature-flag settings."""

    run: bool = Field(default=True)
    """Whether to run the web API service (includes healthcheck and UI backend)."""

    run_ui: bool = Field(default=True)
    """Whether to serve the web UI dashboard. Only used when run is True."""

    ui_hot_reload: bool = Field(default=False)
    """Watch web UI static files and templates for changes and push live reloads to the browser."""

    host: str = Field(default="0.0.0.0")
    """Host to bind the web API server to."""

    port: int = Field(default=8126)
    """Port to run the web API server on."""

    cors_origins: tuple[str, ...] = Field(default=("http://localhost:3000", "http://localhost:5173"))
    """Allowed CORS origins for the web API, typically the UI dev server."""

    event_buffer_size: int = Field(default=500)
    """Maximum number of recent events to keep in the RuntimeQueryService ring buffer."""

    log_buffer_size: int = Field(default=2000)
    """Maximum number of log entries to keep in the LogCaptureHandler ring buffer."""

    job_history_size: int = Field(default=1000)
    """Maximum number of job execution records to keep."""


class AppsConfig(ExcludeExtrasMixin, BaseModel):
    """App directory, auto-detection, exclusion, manifest, and raw-app-dict settings.

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

    autodetect: bool = Field(default=True)
    """Whether to automatically detect apps in the app directory."""

    extend_exclude_dirs: tuple[str, ...] = Field(default_factory=tuple)
    """Additional directories to exclude when auto-detecting apps in the app directory."""

    exclude_dirs: tuple[str, ...] = Field(
        default_factory=lambda data: (
            *data.get("extend_exclude_dirs", ()),
            *AUTODETECT_EXCLUDE_DIRS_DEFAULT,
        )
    )
    """Directories to exclude when auto-detecting apps. Prefer extend_exclude_dirs to avoid
    removing the defaults."""

    manifests: dict[str, AppManifest] = Field(default_factory=dict)
    """Validated app manifests, keyed by app name."""

    apps: dict[str, RawAppDict] = Field(default_factory=dict)
    """Raw configuration for Hassette apps, keyed by app name."""

    directory: Path = Field(default_factory=lambda: Path.cwd() / "apps")
    """Directory to load user apps from."""

    @model_validator(mode="before")
    @classmethod
    def extract_app_definitions(cls, data: Any) -> Any:
        """Separate app-definition dicts from known config fields."""
        if not isinstance(data, dict):
            return data
        data = dict(data)
        known = set(cls.model_fields)
        app_defs: dict[str, Any] = {}
        for key in list(data):
            if key not in known and isinstance(data[key], dict):
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


class SchedulerConfig(ExcludeExtrasMixin, BaseModel):
    """Scheduler delay, threshold, and job-timeout settings."""

    min_delay_seconds: int | float = Field(default=1)
    """Minimum delay between scheduled jobs."""

    max_delay_seconds: int | float = Field(default=30)
    """Maximum delay between scheduled jobs."""

    default_delay_seconds: int | float = Field(default=15)
    """Default delay between scheduled jobs."""

    behind_schedule_threshold_seconds: int | float = Field(default=5)
    """Threshold in seconds before a 'behind schedule' warning is logged for a job."""

    job_timeout_seconds: float | None = Field(default=600.0)
    """Default timeout in seconds for scheduled job execution. ``None`` disables the default timeout.
    Individual jobs can override via ``timeout=`` or ``timeout_disabled=True``."""

    @field_validator("job_timeout_seconds", mode="before")
    @classmethod
    def validate_timeouts(cls, value: Any) -> float | None:
        """Validate that job_timeout_seconds is None or a positive number."""
        if value is None:
            return None
        if isinstance(value, bool):
            raise ValueError("timeout must be None or a positive number")
        val = float(value)
        if val <= 0:
            raise ValueError("timeout must be None or a positive number")
        return val


class FileWatcherConfig(ExcludeExtrasMixin, BaseModel):
    """File watcher debounce, step, and enable/disable settings."""

    debounce_milliseconds: int = Field(default=3000)
    """Debounce time for file watcher events in milliseconds."""

    step_milliseconds: int = Field(default=500)
    """Time to wait for additional file changes before emitting event in milliseconds."""

    watch_files: bool = Field(default=True)
    """Whether to watch files for changes and reload apps automatically."""
