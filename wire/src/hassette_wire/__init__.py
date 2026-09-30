"""Wire contract for the Hassette HTTP and WebSocket API.

This package holds every model, enum, and Literal that a served HTTP response or WebSocket
message uses: request/response bodies, WS payloads, and the vocabulary they're built from
(status enums, open-set Literals, and ``CliFormat``). Consumers — the server, the client
package, and the HA companion integration — import from the package root
(``from hassette_wire import JobSummary``), not from a submodule.

A wire field added after the first published ``hassette-wire`` release must be optional with a
default, so a client built against a newer release — one that already expects the field — can
still parse a response from a server still running the older release that hasn't added it yet.
Adding a new enum member or a new value to an open-set Literal is a version-skew change in the
opposite direction: an older client parsing a newer server's response needs to tolerate a value
it doesn't recognize. The client package's lenient parsing is what makes that direction safe.
"""

from hassette_wire.apps import (
    ActionResponse,
    AppConfigResponse,
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppSourceResponse,
    AppStatusResponse,
)
from hassette_wire.auth import MAX_SESSION_TOKEN_LENGTH, SessionRequest, SessionResponse
from hassette_wire.cli_format import CliFormat, CliFormatStyle
from hassette_wire.config import ConfigSchemaResponse
from hassette_wire.enums import BackpressurePolicy, ExecutionMode, ExecutionStatus, ManifestStatus, ResourceStatus
from hassette_wire.health import (
    BootIssueResponse,
    LivenessResponse,
    ReadinessResponse,
    ServiceInfoResponse,
    SystemStatusResponse,
)
from hassette_wire.literals import (
    LOG_LEVEL_TYPE,
    ErrorRateClass,
    HealthStatus,
    ListenerKind,
    QuerySourceTier,
    SourceTier,
    SystemHealthStatus,
)
from hassette_wire.logs import LogEntryResponse, LogLevelRequest, LogLevelResponse, LogsByExecutionResponse
from hassette_wire.telemetry import (
    ActivityBucket,
    ActivityFeedEntry,
    AppHealthResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    Execution,
    JobSummary,
    JobTriggerResponse,
    ListenerWithSummary,
    TelemetryStatusResponse,
)
from hassette_wire.ws import (
    AppManifestsChangedData,
    AppManifestsChangedWsMessage,
    AppStatusChangedData,
    AppStatusChangedWsMessage,
    ConnectedPayload,
    ConnectedWsMessage,
    ConnectivityData,
    ConnectivityWsMessage,
    ExecutionCompletedData,
    ExecutionCompletedWsMessage,
    LogHintWsMessage,
    ServiceStatusData,
    ServiceStatusWsMessage,
    WsServerMessage,
)

__all__ = [
    "LOG_LEVEL_TYPE",
    "MAX_SESSION_TOKEN_LENGTH",
    "ActionResponse",
    "ActivityBucket",
    "ActivityFeedEntry",
    "AppConfigResponse",
    "AppHealthResponse",
    "AppInstanceResponse",
    "AppManifestListResponse",
    "AppManifestResponse",
    "AppManifestsChangedData",
    "AppManifestsChangedWsMessage",
    "AppSourceResponse",
    "AppStatusChangedData",
    "AppStatusChangedWsMessage",
    "AppStatusResponse",
    "BackpressurePolicy",
    "BootIssueResponse",
    "CliFormat",
    "CliFormatStyle",
    "ConfigSchemaResponse",
    "ConnectedPayload",
    "ConnectedWsMessage",
    "ConnectivityData",
    "ConnectivityWsMessage",
    "DashboardAppGridEntry",
    "DashboardAppGridResponse",
    "ErrorRateClass",
    "Execution",
    "ExecutionCompletedData",
    "ExecutionCompletedWsMessage",
    "ExecutionMode",
    "ExecutionStatus",
    "HealthStatus",
    "JobSummary",
    "JobTriggerResponse",
    "ListenerKind",
    "ListenerWithSummary",
    "LivenessResponse",
    "LogEntryResponse",
    "LogHintWsMessage",
    "LogLevelRequest",
    "LogLevelResponse",
    "LogsByExecutionResponse",
    "ManifestStatus",
    "QuerySourceTier",
    "ReadinessResponse",
    "ResourceStatus",
    "ServiceInfoResponse",
    "ServiceStatusData",
    "ServiceStatusWsMessage",
    "SessionRequest",
    "SessionResponse",
    "SourceTier",
    "SystemHealthStatus",
    "SystemStatusResponse",
    "TelemetryStatusResponse",
    "WsServerMessage",
]
