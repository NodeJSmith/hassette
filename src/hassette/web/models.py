"""Pydantic response models for the Hassette Web API."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from hassette.schemas.domain_models import AppStatusChangedData, ConnectivityData, ServiceStatusData, StateChangedData
from hassette.types.enums import DEFAULT_BACKPRESSURE_POLICY, DEFAULT_OVERLAP_MODE, ResourceStatus
from hassette.types.types import LOG_LEVEL_TYPE, CliFormat, SourceTier

ManifestStatus = Literal["disabled", "blocked", "running", "failed", "stopped"]
"""Status values for app manifests (manifest-scoped, 5 values).

Verified against ``src/hassette/core/app_registry.py`` status derivation logic.
"""

ErrorRateClass = Literal["good", "warn", "bad"]
"""CSS classification for error rate percentage.

Verified against ``classify_error_rate()`` return values in ``telemetry_helpers.py``.
"""

HealthStatus = Literal["excellent", "good", "warning", "critical"]
"""Health bar classification from success-rate percentage.

Verified against ``classify_health_bar()`` return values in ``telemetry_helpers.py``.
Does NOT include ``"unknown"`` — zero-invocation apps return ``"excellent"``.
"""

ListenerKind = Literal["state change", "service call", "event"]
"""Kind of listener event (3 values).

Verified against ``listener_kind_from_topic()`` return values in ``mappers.py``.
"""

SystemHealthStatus = Literal["ok", "degraded", "starting"]
"""System-level health status (3 values).

Mirrors ``SystemStatus.status`` from ``src/hassette/schemas/domain_models.py``.
"""


class BootIssueResponse(BaseModel):
    """A boot-time issue entry in the system status response."""

    severity: Literal["err", "warn"]
    label: str
    detail: str


class ServiceInfoResponse(BaseModel):
    """Structured info for one internal service."""

    name: str
    status: ResourceStatus
    role: str = ""
    """Role of the service (e.g. 'service', 'resource'). Empty string when not available."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted (cooling state), or None."""


class SystemStatusResponse(BaseModel):
    status: SystemHealthStatus
    websocket_connected: bool
    uptime_seconds: Annotated[float, CliFormat("uptime")]
    entity_count: int
    app_count: int
    services_running: list[str]
    services: list[ServiceInfoResponse] = Field(default_factory=list)
    version: str = ""
    boot_issues: list[BootIssueResponse] = Field(default_factory=list)
    log_records_dropped: int = 0


class LivenessResponse(BaseModel):
    """Response model for GET /api/health/live."""

    status: Literal["live"] = "live"


class ReadinessResponse(BaseModel):
    """Response model for GET /api/health/ready."""

    status: SystemHealthStatus
    ready: bool


class EntityStateResponse(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str | None
    last_updated: str | None


class EntityListResponse(BaseModel):
    count: int
    entities: list[EntityStateResponse]


class AppInstanceResponse(BaseModel):
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: ResourceStatus
    error_message: str | None = None
    error_traceback: str | None = None
    owner_id: str | None = None


class AppStatusResponse(BaseModel):
    total: int
    running: int
    failed: int
    apps: list[AppInstanceResponse]
    only_app: str | None = None


class AppManifestResponse(BaseModel):
    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    auto_loaded: bool
    autostart: bool = True
    status: ManifestStatus
    block_reason: str | None = None
    instance_count: int = Field(
        default=0,
        description="Tracked instances (running/failed). 0 = none tracked (stopped/disabled).",
    )
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    recent_invocations_1h: int = Field(
        default=0,
        description="Total handler invocations in the last hour across all instances.",
    )


class AppManifestListResponse(BaseModel):
    total: int
    running: int
    failed: int
    stopped: int
    disabled: int
    blocked: int
    manifests: list[AppManifestResponse]
    only_app: str | None = None


class EventEntry(BaseModel):
    type: str
    entity_id: str | None = None
    timestamp: float
    data: dict[str, Any] = Field(default_factory=dict)


class WsMessage(BaseModel):
    type: str
    data: dict[str, Any]


class LogEntryResponse(BaseModel):
    seq: int
    timestamp: float
    level: LOG_LEVEL_TYPE
    logger_name: str
    func_name: str | None = None
    lineno: int | None = None
    message: str
    exc_info: str | None = None
    app_key: str | None = None
    execution_id: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None
    source_tier: SourceTier | None = None


class LogsByExecutionResponse(BaseModel):
    """Response for GET /api/executions/{execution_id}."""

    records: list[LogEntryResponse]
    truncated: bool
    retention_expired: bool


class LogLevelRequest(BaseModel):
    """Request body for PUT /api/logs/level."""

    logger: str
    level: str


class LogLevelResponse(BaseModel):
    """Response for PUT /api/logs/level."""

    logger: str
    effective_level: str


class ConnectedPayload(BaseModel):
    uptime_seconds: float
    entity_count: int
    app_count: int
    version: str = ""


class AppStatusChangedWsMessage(BaseModel):
    type: Literal["app_status_changed"]
    data: AppStatusChangedData
    timestamp: float


class LogWsMessage(BaseModel):
    type: Literal["log"]
    data: LogEntryResponse
    timestamp: float


class ConnectedWsMessage(BaseModel):
    type: Literal["connected"]
    data: ConnectedPayload
    timestamp: float


class ConnectivityWsMessage(BaseModel):
    type: Literal["connectivity"]
    data: ConnectivityData
    timestamp: float


class StateChangedWsMessage(BaseModel):
    type: Literal["state_changed"]
    data: StateChangedData
    timestamp: float


class ServiceStatusWsMessage(BaseModel):
    type: Literal["service_status"]
    data: ServiceStatusData
    timestamp: float


class ExecutionCompletedData(BaseModel):
    """Payload for execution_completed WebSocket messages.

    ``kind`` discriminates handler invocations from job executions.
    ``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.
    """

    kind: Literal["handler", "job"]
    app_key: str
    instance_index: int
    status: str
    duration_ms: float
    error_type: str | None = None
    listener_id: int | None = None
    job_id: int | None = None
    thread_leaked: bool = False


class ExecutionCompletedWsMessage(BaseModel):
    type: Literal["execution_completed"]
    data: list[ExecutionCompletedData]
    """Per-drain batch: all executions persisted in one ``drain_and_persist()`` cycle."""
    timestamp: float


WsServerMessage = Annotated[
    AppStatusChangedWsMessage
    | LogWsMessage
    | ConnectedWsMessage
    | ConnectivityWsMessage
    | StateChangedWsMessage
    | ServiceStatusWsMessage
    | ExecutionCompletedWsMessage,
    Field(discriminator="type"),
]


class AppHealthResponse(BaseModel):
    """Health metrics for a single app instance."""

    error_rate: float
    error_rate_class: ErrorRateClass
    handler_avg_duration: Annotated[float, CliFormat("duration_ms")]
    job_avg_duration: Annotated[float, CliFormat("duration_ms")]
    last_activity_ts: Annotated[float | None, CliFormat("relative_time")]
    health_status: HealthStatus


class ListenerWithSummary(BaseModel):
    """Listener metrics enriched with human-readable handler summary."""

    listener_id: int
    app_key: str
    instance_index: int = 0
    topic: str
    listener_kind: ListenerKind = "event"
    handler_method: str
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    avg_duration_ms: float = 0.0
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None
    total_duration_ms: float = 0.0
    predicate_description: str | None = None
    human_description: str | None = None
    debounce: float | None = None
    throttle: float | None = None
    once: int = 0
    priority: int = 0
    last_invoked_at: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None
    last_error_traceback: str | None = None
    timed_out: int = 0
    thread_leaked: int = 0
    source_location: str = ""
    registration_source: str | None = None
    handler_summary: str = ""
    source_tier: SourceTier = "app"
    immediate: int = 0
    duration: float | None = None
    entity_id: str | None = None
    mode: str = DEFAULT_OVERLAP_MODE
    suppressed_count: int = 0
    dropped_count: int = 0
    backpressure_dropped_count: int = 0
    backpressure: str = DEFAULT_BACKPRESSURE_POLICY


class ActivityBucket(BaseModel):
    """A single time-window bucket for the sparkline chart."""

    ok: int
    """Number of successful invocations/executions in this bucket."""

    err: int
    """Number of error/timed-out invocations/executions in this bucket."""


class DashboardAppGridEntry(BaseModel):
    """Per-app health entry for the dashboard grid."""

    app_key: str
    status: ManifestStatus
    display_name: str
    instance_count: int = Field(
        default=0,
        description="Tracked instances (running/failed). 0 = none tracked (stopped/disabled).",
    )
    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_timed_out: int = 0
    total_executions: int
    total_job_errors: int
    total_job_timed_out: int = 0
    avg_duration_ms: float
    last_activity_ts: float | None
    health_status: HealthStatus
    error_rate: float
    error_rate_class: ErrorRateClass
    activity_buckets: list[ActivityBucket] = Field(default_factory=list)
    """Per-app sparkline buckets (ok/err counts per time window)."""
    last_error_message: str | None = None
    last_error_type: str | None = None
    last_error_ts: float | None = None


class DashboardAppGridResponse(BaseModel):
    """Dashboard app grid with per-app health data."""

    apps: list[DashboardAppGridEntry]


class TelemetryStatusResponse(BaseModel):
    """Health check response for the telemetry database."""

    degraded: bool
    dropped_overflow: int = 0
    dropped_exhausted: int = 0
    dropped_shutdown: int = 0
    error_handler_failures: int = 0


class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload)."""

    status: str
    app_key: str
    action: str


class WebApiConfigResponse(BaseModel):
    """Sanitized web API configuration fields."""

    run: bool
    run_ui: bool
    ui_hot_reload: bool
    host: str
    port: int
    cors_origins: list[str]
    event_buffer_size: int
    log_buffer_size: int
    job_history_size: int


class LoggingConfigResponse(BaseModel):
    """Sanitized logging configuration fields."""

    log_level: str
    web_api: str


class LifecycleConfigResponse(BaseModel):
    """Sanitized lifecycle configuration fields."""

    startup_timeout_seconds: int
    app_startup_timeout_seconds: int
    app_shutdown_timeout_seconds: int


class AppsConfigResponse(BaseModel):
    """Sanitized apps configuration fields (config group sub-response)."""

    autodetect: bool
    directory: str


class SchedulerConfigResponse(BaseModel):
    """Sanitized scheduler configuration fields."""

    min_delay_seconds: int | float
    max_delay_seconds: int | float
    default_delay_seconds: int | float


class FileWatcherConfigResponse(BaseModel):
    """Sanitized file watcher configuration fields."""

    watch_files: bool
    debounce_milliseconds: int


class ConfigResponse(BaseModel):
    """Sanitized configuration response organized by config group."""

    dev_mode: bool
    base_url: str
    asyncio_debug_mode: bool
    allow_reload_in_prod: bool
    data_dir: str
    config_dir: str
    web_api: WebApiConfigResponse
    logging: LoggingConfigResponse
    lifecycle: LifecycleConfigResponse
    apps: AppsConfigResponse
    scheduler: SchedulerConfigResponse
    file_watcher: FileWatcherConfigResponse


class AppConfigResponse(BaseModel):
    """Response model for GET /apps/{app_key}/config."""

    app_key: str
    filename: str
    class_name: str
    enabled: bool
    app_config: dict[str, Any] | list[dict[str, Any]]
    config_schema: dict[str, Any] | None = None


class AppSourceResponse(BaseModel):
    """Response model for GET /apps/{app_key}/source."""

    app_key: str
    filename: str
    content: str
    line_count: int
