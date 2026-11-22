from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.apps import DeclaredEntity, NeedsRestart
from hassette_wire.enums import OpenAppStatus, OpenExecutionStatus, OpenResourceStatus
from hassette_wire.literals import OpenExecutionKind


class AppStatusChangedData(BaseModel):
    """An app instance changed lifecycle status.

    Apply it only when ``status_revision`` is strictly greater than the ``AppSummary.status_revision`` of the row it
    updates; on a tie the summary wins. The ``exception*`` fields describe the error that caused the change, and
    are ``None`` when no error did.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    app_key: str
    instance_name: str
    status: OpenResourceStatus
    status_revision: int
    """The app-status revision this change was written at; comparable with ``AppSummary.status_revision``."""
    boot_id: str
    """Identifies the hassette boot that sent the message; a new value means the server restarted. Ordering doesn't
    need it, since ``status_revision`` keeps increasing across restarts; it lets a client reset state it keeps per
    server process."""
    app_status: OpenAppStatus
    """The app's rollup status after this change, equal to the ``AppSummary.status`` read at ``status_revision``."""
    previous_status: OpenResourceStatus | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    needs_restart: NeedsRestart | None = None
    """Set when this change flagged the instance needs-restart (only a ``failed`` change can), so a client can show
    it with the status."""


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
    """A framework service changed lifecycle status.

    The ``exception*`` fields describe the error that caused the change, and are ``None`` when no error did.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    resource_name: str
    status: OpenResourceStatus
    previous_status: OpenResourceStatus | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    ready: bool = False
    """Whether the service had signalled readiness at the time of this status event."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""


class ConnectedData(BaseModel):
    """Server state sent once, as the first message after a WebSocket connection opens.

    ``version`` is the server's hassette version; a client can compare it with its own to detect an upgrade.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    uptime_seconds: float
    entity_count: int
    app_count: int
    """Number of app instances currently tracked (starting, running, or failed), not the number of configured apps.

    Same meaning as ``SystemStatusResponse.app_count``."""
    version: str = ""


class AppStatusChangedWsMessage(BaseModel):
    """Envelope for ``AppStatusChangedData``."""

    type: Literal["app_status_changed"]
    data: AppStatusChangedData
    timestamp: float


class LogHintWsMessage(BaseModel):
    """New log records exist; refetch them over HTTP.

    Carries no records. Sent only to clients that subscribed to logs.
    """

    type: Literal["log_hint"]
    timestamp: float


class ConnectedWsMessage(BaseModel):
    """Envelope for ``ConnectedData``."""

    type: Literal["connected"]
    data: ConnectedData
    timestamp: float


class ConnectivityWsMessage(BaseModel):
    """Envelope for ``ConnectivityData``."""

    type: Literal["connectivity"]
    data: ConnectivityData
    timestamp: float


class ServiceStatusWsMessage(BaseModel):
    """Envelope for ``ServiceStatusData``."""

    type: Literal["service_status"]
    data: ServiceStatusData
    timestamp: float


class AppsChangedWsMessage(BaseModel):
    """Envelope for ``AppsChangedData``."""

    type: Literal["apps_changed"]
    data: AppsChangedData
    timestamp: float


class EntityStateChangedData(BaseModel):
    """One app-declared entity's committed state changed.

    ``boot_id`` and ``entity_revision`` are the same counters ``GET /api/apps`` reports. Apply this message only
    when its ``entity_revision`` is newer than the last one applied for the same ``boot_id``; revisions skip values,
    and a lost message is repaired only by the next listing fetch. Declaration commits send no message: entities
    appear and disappear only through the listing.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    boot_id: str
    """Identifies the hassette boot that sent the message; a new value means the server restarted."""
    entity_revision: int
    """The hassette-wide entity revision this change was committed at."""
    app_key: str
    instance_name: str
    entity: DeclaredEntity
    """The entity's full description and new state, as the listing reports it."""


class EntityStateChangedWsMessage(BaseModel):
    """Envelope for ``EntityStateChangedData``."""

    type: Literal["entity_state_changed"]
    data: EntityStateChangedData
    timestamp: float


class ExecutionCompletedData(BaseModel):
    """Payload for execution_completed WebSocket messages.

    ``kind`` discriminates handler invocations from job executions.
    ``listener_id`` is set when ``kind='handler'``; ``job_id`` when ``kind='job'``.
    """

    kind: OpenExecutionKind
    app_key: str
    status: OpenExecutionStatus
    duration_ms: float
    error_type: str | None = None
    listener_id: int | None = None
    job_id: int | None = None
    thread_leaked: bool = False


class ExecutionCompletedWsMessage(BaseModel):
    """Envelope for a batch of ``ExecutionCompletedData``."""

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
    | AppsChangedWsMessage
    | EntityStateChangedWsMessage,
    Field(discriminator="type"),
]
