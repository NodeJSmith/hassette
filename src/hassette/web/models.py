"""Pydantic response models for the Hassette Web API."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from hassette.core.domain_models import AppStatusChangedData, ConnectivityData, ServiceStatusData, StateChangedData
from hassette.core.telemetry_models import SessionRecord
from hassette.types.types import SourceTier


class SystemStatusResponse(BaseModel):
    status: str
    websocket_connected: bool
    uptime_seconds: float
    entity_count: int
    app_count: int
    services_running: list[str]


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
    status: str
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
    status: str
    block_reason: str | None = None
    instance_count: int = Field(
        default=0,
        description="Tracked instances (running/failed). 0 = none tracked (stopped/disabled).",
    )
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None


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
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    exc_info: str | None = None
    app_key: str | None = None


class ScheduledJobResponse(BaseModel):
    job_id: int
    name: str
    owner_id: str
    next_run: str
    repeat: bool
    cancelled: bool
    trigger_type: Literal["interval", "cron", "once", "after", "custom"] | None
    trigger_detail: str | None = None


# ---------------------------------------------------------------------------
# Typed WebSocket message models
# ---------------------------------------------------------------------------


class ConnectedPayload(BaseModel):
    session_id: int | None = None
    entity_count: int
    app_count: int


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


WsServerMessage = Annotated[
    AppStatusChangedWsMessage
    | LogWsMessage
    | ConnectedWsMessage
    | ConnectivityWsMessage
    | StateChangedWsMessage
    | ServiceStatusWsMessage,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Typed error entry models (for get_recent_errors)
# ---------------------------------------------------------------------------


class HandlerErrorEntry(BaseModel):
    kind: Literal["handler"] = "handler"
    listener_id: int | None
    topic: str | None
    handler_method: str | None
    error_message: str | None
    error_type: str | None
    execution_start_ts: float
    app_key: str | None
    source_tier: SourceTier = "app"


class JobErrorEntry(BaseModel):
    kind: Literal["job"] = "job"
    job_id: int | None
    job_name: str | None
    error_message: str | None
    error_type: str | None
    execution_start_ts: float
    app_key: str | None
    source_tier: SourceTier = "app"


RecentErrorEntry = Annotated[HandlerErrorEntry | JobErrorEntry, Field(discriminator="kind")]


# ---------------------------------------------------------------------------
# Telemetry endpoint response models
# ---------------------------------------------------------------------------


class AppHealthResponse(BaseModel):
    """Health metrics for a single app instance."""

    error_rate: float
    error_rate_class: str
    handler_avg_duration: float
    job_avg_duration: float
    last_activity_ts: float | None
    health_status: str


class ListenerWithSummary(BaseModel):
    """Listener metrics enriched with human-readable handler summary."""

    listener_id: int
    app_key: str
    instance_index: int = 0
    topic: str
    handler_method: str
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    avg_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
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
    source_location: str = ""
    registration_source: str | None = None
    handler_summary: str = ""
    source_tier: SourceTier = "app"


class DashboardKpisResponse(BaseModel):
    """Global KPI metrics for the dashboard strip."""

    total_handlers: int
    total_jobs: int
    total_invocations: int
    total_executions: int
    total_errors: int
    total_job_errors: int
    avg_handler_duration_ms: float
    avg_job_duration_ms: float
    error_rate: float
    error_rate_class: str
    uptime_seconds: float | None = None


class DashboardAppGridEntry(BaseModel):
    """Per-app health entry for the dashboard grid."""

    app_key: str
    status: str
    display_name: str
    instance_count: int = Field(
        default=0,
        description="Tracked instances (running/failed). 0 = none tracked (stopped/disabled).",
    )
    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_executions: int
    total_job_errors: int
    avg_duration_ms: float
    last_activity_ts: float | None
    health_status: str
    error_rate: float
    error_rate_class: str


class DashboardAppGridResponse(BaseModel):
    """Dashboard app grid with per-app health data."""

    apps: list[DashboardAppGridEntry]


class DashboardErrorsResponse(BaseModel):
    """Recent errors for the dashboard error feed."""

    errors: list[HandlerErrorEntry | JobErrorEntry]


class FrameworkSummaryResponse(BaseModel):
    """Combined framework KPIs + recent errors in one atomic response."""

    total_errors: int
    total_job_errors: int
    errors: list[HandlerErrorEntry | JobErrorEntry]


SessionListEntry = SessionRecord


class TelemetryStatusResponse(BaseModel):
    """Health check response for the telemetry database."""

    degraded: bool
    dropped_overflow: int = 0
    dropped_exhausted: int = 0
    dropped_no_session: int = 0
    dropped_shutdown: int = 0


class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload)."""

    status: str
    app_key: str
    action: str


class ConfigResponse(BaseModel):
    """Sanitized configuration response (allowlisted fields only)."""

    dev_mode: bool = False
    log_level: str = "INFO"
    base_url: str = ""
    run_web_api: bool = True
    run_web_ui: bool = True
    web_api_host: str = "0.0.0.0"
    web_api_port: int = 8126
    web_api_cors_origins: list[str] = Field(default_factory=list)
    web_api_event_buffer_size: int = 500
    web_api_log_buffer_size: int = 2000
    web_api_job_history_size: int = 1000
    web_api_log_level: str = "INFO"
    autodetect_apps: bool = True
    startup_timeout_seconds: int = 10
    app_startup_timeout_seconds: int = 20
    app_shutdown_timeout_seconds: int = 10
    watch_files: bool = True
    file_watcher_debounce_milliseconds: int = 3000
    scheduler_min_delay_seconds: int = 1
    scheduler_max_delay_seconds: int = 30
    scheduler_default_delay_seconds: int = 15
    asyncio_debug_mode: bool = False
    allow_reload_in_prod: bool = False
    web_ui_hot_reload: bool = False
