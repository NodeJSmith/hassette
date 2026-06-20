"""Pure-data schemas package for Hassette web-facing types.

This package contains data types that are consumed by both ``hassette.core``
(as producers) and ``hassette.web`` (as consumers). Placing them here, below
both, breaks the ``web → core`` import cycle.

Import policy: ``schemas`` may import ONLY ``hassette.types``, ``hassette.const``,
and ``hassette.utils``. No ``core``, no service logic.
"""

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.schemas.domain_models import (
    AppStatusChangedData,
    BootIssue,
    ConnectivityData,
    ServiceInfo,
    ServiceStatusData,
    StateChangedData,
    SystemStatus,
)
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS
from hassette.schemas.telemetry_models import (
    ActivityFeedEntry,
    AppHealthSummary,
    AppLastError,
    BlockingEvent,
    Execution,
    GlobalSummary,
    HandlerErrorRecord,
    JobErrorRecord,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
    ListenerSummary,
    LogRecord,
    SessionRecord,
    SessionSummary,
    SlowHandlerRecord,
)

__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "DEFAULT_SPARKLINE_BUCKETS",
    "ActivityFeedEntry",
    "AppFullSnapshot",
    "AppHealthSummary",
    "AppInstanceInfo",
    "AppLastError",
    "AppManifestInfo",
    "AppStatusChangedData",
    "AppStatusSnapshot",
    "BlockingEvent",
    "BootIssue",
    "ConnectivityData",
    "Execution",
    "GlobalSummary",
    "HandlerErrorRecord",
    "JobErrorRecord",
    "JobGlobalStats",
    "JobSummary",
    "ListenerGlobalStats",
    "ListenerSummary",
    "LiveCounts",
    "LogRecord",
    "ServiceInfo",
    "ServiceStatusData",
    "SessionRecord",
    "SessionSummary",
    "SlowHandlerRecord",
    "StateChangedData",
    "SystemStatus",
]
