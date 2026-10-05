from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.enums import OpenExecutionStatus, OpenResourceRole, OpenResourceStatus
from hassette_wire.literals import OpenExecutionKind


class AppStatusChangedData(BaseModel):
    """Payload for an app lifecycle state-change event broadcast over WebSocket.

    Mirrors ``events.hassette.AppStateChangePayload`` exactly.
    """

    app_key: str
    index: int
    status: OpenResourceStatus
    previous_status: OpenResourceStatus | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class ConnectivityData(BaseModel):
    """Payload for a Home Assistant WebSocket connectivity event."""

    connected: bool


class AppsChangedData(BaseModel):
    """Payload for an app-list refresh broadcast over WebSocket.

    Carries no fields and does not identify which apps changed — it is a refetch
    signal, not a diff. Clients should treat receipt as "app status may be
    stale, refetch" rather than inspect the payload.
    """


class ServiceStatusData(BaseModel):
    """Payload for an internal service status-change event broadcast over WebSocket.

    Mirrors ``events.hassette.ServiceStatusPayload``.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    resource_name: str
    role: OpenResourceRole
    status: OpenResourceStatus
    previous_status: OpenResourceStatus | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted.

    Populated for ``EXHAUSTED_COOLING`` events (the service is in a long cooldown
    and will retry at this time). ``None`` for ``EXHAUSTED_DEAD`` and all other
    statuses. The frontend uses this to display a live countdown timer.
    """
    ready: bool = False
    """Whether the service had signalled readiness at the time of this status event."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""


class ConnectedPayload(BaseModel):
    uptime_seconds: float
    entity_count: int
    app_count: int
    version: str = ""


class AppStatusChangedWsMessage(BaseModel):
    type: Literal["app_status_changed"]
    data: AppStatusChangedData
    timestamp: float


class LogHintWsMessage(BaseModel):
    type: Literal["log_hint"]
    timestamp: float


class ConnectedWsMessage(BaseModel):
    type: Literal["connected"]
    data: ConnectedPayload
    timestamp: float


class ConnectivityWsMessage(BaseModel):
    type: Literal["connectivity"]
    data: ConnectivityData
    timestamp: float


class ServiceStatusWsMessage(BaseModel):
    type: Literal["service_status"]
    data: ServiceStatusData
    timestamp: float


class AppsChangedWsMessage(BaseModel):
    type: Literal["apps_changed"]
    data: AppsChangedData
    timestamp: float


class ExecutionCompletedData(BaseModel):
    """Payload for execution_completed WebSocket messages.

    ``kind`` discriminates handler invocations from job executions.
    ``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.
    """

    kind: OpenExecutionKind
    app_key: str
    instance_index: int
    status: OpenExecutionStatus
    duration_ms: float
    error_type: str | None = None
    listener_id: int | None = None
    job_id: int | None = None
    thread_leaked: bool = False


class ExecutionCompletedWsMessage(BaseModel):
    model_config = ConfigDict(use_attribute_docstrings=True)

    type: Literal["execution_completed"]
    data: list[ExecutionCompletedData]
    """App-tier executions persisted since the previous message, delivered together in one batch."""
    timestamp: float


WsServerMessage = Annotated[
    AppStatusChangedWsMessage
    | LogHintWsMessage
    | ConnectedWsMessage
    | ConnectivityWsMessage
    | ServiceStatusWsMessage
    | ExecutionCompletedWsMessage
    | AppsChangedWsMessage,
    Field(discriminator="type"),
]
