"""Pure-data schemas package for Hassette web-facing types.

This package contains data types that are consumed by both ``hassette.core``
(as producers) and ``hassette.web`` (as consumers). Placing them here, below
both, breaks the ``web → core`` import cycle.

Import policy: within ``hassette``, ``schemas`` may import ONLY ``hassette.types``,
``hassette.const``, and ``hassette.utils`` — no ``core``, no service logic. Third-party
(pydantic) and stdlib (``importlib.metadata``) imports are fine; the rule is about
keeping ``schemas`` below ``core``/``web`` in the layer DAG.

Telemetry DB query-result models are split by domain across sibling modules:

- ``listener_models.py`` — per-listener summaries, stats, and error records
- ``execution_models.py`` — unified execution records and activity feed
- ``job_models.py`` — per-job summaries, stats, and error records
- ``summary_models.py`` — app-health and global aggregates
- ``log_models.py`` — log records and blocking events
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from hassette.schemas.app_snapshots import AppFullSnapshot, AppInstanceInfo, AppManifestInfo, AppStatusSnapshot
from hassette.schemas.domain_models import (
    AppStatusChangedData,
    BootIssue,
    ConnectivityData,
    ServiceInfo,
    ServiceStatusData,
    SystemStatus,
)
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS
from hassette.types.enums import ManifestStatus

__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "DEFAULT_SPARKLINE_BUCKETS",
    "AppFullSnapshot",
    "AppInstanceInfo",
    "AppManifestInfo",
    "AppStatusChangedData",
    "AppStatusSnapshot",
    "BootIssue",
    "ConnectivityData",
    "LiveCounts",
    "ManifestStatus",
    "ServiceInfo",
    "ServiceStatusData",
    "SystemStatus",
]
