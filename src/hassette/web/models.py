"""Pydantic response models for the Hassette Web API."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class SystemStatusResponse(BaseModel):
    status: str
    websocket_connected: bool
    uptime_seconds: float | None
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
    instance_count: int = 0
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
    trigger_type: str
    trigger_detail: str | None = None


class JobExecutionResponse(BaseModel):
    job_id: int
    job_name: str
    owner_id: str
    started_at: float
    duration_ms: float
    status: str
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None


class ListenerMetricsResponse(BaseModel):
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
    debounce: float | None = None
    throttle: float | None = None
    once: bool = False
    priority: int = 0
    last_invoked_at: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None


class BusMetricsSummaryResponse(BaseModel):
    total_listeners: int
    total_invocations: int
    total_successful: int
    total_failed: int
    total_di_failures: int
    total_cancelled: int


class SchedulerSummaryResponse(BaseModel):
    total_jobs: int
    active: int
    cancelled: int
    repeating: int


# ---------------------------------------------------------------------------
# Typed WebSocket message models
# ---------------------------------------------------------------------------


class AppStatusChangedPayload(BaseModel):
    """Mirrors ``events.hassette.AppStateChangePayload`` exactly."""

    app_key: str
    index: int
    status: str
    previous_status: str | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class ConnectedPayload(BaseModel):
    session_id: int | None = None
    entity_count: int
    app_count: int


class ConnectivityPayload(BaseModel):
    connected: bool


class StateChangedPayload(BaseModel):
    entity_id: str
    new_state: Any
    old_state: Any


class WsServiceStatusPayload(BaseModel):
    """Mirrors ``events.hassette.ServiceStatusPayload``."""

    resource_name: str
    role: str
    status: str
    previous_status: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class AppStatusChangedWsMessage(BaseModel):
    type: Literal["app_status_changed"]
    data: AppStatusChangedPayload
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
    data: ConnectivityPayload
    timestamp: float


class StateChangedWsMessage(BaseModel):
    type: Literal["state_changed"]
    data: StateChangedPayload
    timestamp: float


class ServiceStatusWsMessage(BaseModel):
    type: Literal["service_status"]
    data: WsServiceStatusPayload
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
    listener_id: int
    topic: str
    handler_method: str
    error_message: str
    error_type: str
    timestamp: float
    app_key: str


class JobErrorEntry(BaseModel):
    kind: Literal["job"] = "job"
    job_id: int
    job_name: str
    error_message: str
    error_type: str
    timestamp: float
    app_key: str


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
    handler_summary: str = ""


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
    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_executions: int
    total_job_errors: int
    avg_duration_ms: float
    last_activity_ts: float | None
    health_status: str


class DashboardAppGridResponse(BaseModel):
    """Dashboard app grid with per-app health data."""

    apps: list[DashboardAppGridEntry]


class DashboardErrorsResponse(BaseModel):
    """Recent errors for the dashboard error feed."""

    errors: list[HandlerErrorEntry | JobErrorEntry]
