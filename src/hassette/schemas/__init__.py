"""Data types and small pure helpers for Hassette web-facing types.

This package contains data types that are consumed by both ``hassette.core``
(as producers) and ``hassette.web`` (as consumers). Placing them here, below
both, breaks the ``web → core`` import cycle.

Import policy: within ``hassette``, ``schemas`` may import ONLY ``hassette.types``,
``hassette.const``, and ``hassette.utils`` — no ``core``, no service logic. ``hassette_wire``,
third-party (pydantic), and stdlib (``importlib.metadata``) imports are fine; the rule is about
keeping ``schemas`` below ``core``/``web`` in the layer DAG.

Telemetry DB query results are typed models rather than raw ``dict`` returns, which prevents
the "column rename -> silent template failure" class of bugs.

Modules:

- ``app_snapshots.py`` — app-registry snapshots (manifests, instances, status tallies)
- ``app_outcomes.py`` — per-instance outcomes of an app lifecycle action
- ``app_config_shape.py`` — shared ``app_config`` normalization and instance-name lookup
- ``live_counts.py`` — live execution counts for bus listeners
- ``query_constants.py`` — telemetry query row limits
- ``listener_models.py`` — per-listener summaries and slow-handler records
- ``execution_models.py`` — the latest-error record read per app by the execution queries
- ``summary_models.py`` — app-health aggregates
- ``log_models.py`` — log records and blocking events
- ``ws_queue.py`` — items on a ``/ws`` client queue (``WsClientSignal``, ``WsQueueItem``)

Served models, WS payloads, and the live system-status snapshot are defined only in
``hassette_wire`` — see that package for ``SystemStatusResponse``, ``ServiceInfo``,
``BootIssue``, and the WS event payload models.
"""

from hassette.schemas.app_snapshots import (
    AppFullSnapshot,
    AppInstanceInfo,
    AppManifestInfo,
    AppStatusSnapshot,
    NeedsRestartInfo,
)
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.query_constants import DEFAULT_QUERY_LIMIT, DEFAULT_SPARKLINE_BUCKETS

__all__ = [
    "DEFAULT_QUERY_LIMIT",
    "DEFAULT_SPARKLINE_BUCKETS",
    "AppFullSnapshot",
    "AppInstanceInfo",
    "AppManifestInfo",
    "AppStatusSnapshot",
    "LiveCounts",
    "NeedsRestartInfo",
]
