"""Factory functions for e2e test mock data.

These build the seed data used by the ``mock_hassette`` session fixture in
``conftest.py``.  Keeping construction here reduces conftest.py to the
fixture scaffolding only and makes individual seed builders reusable.

Split into submodules by concern (manifests, scheduler, telemetry,
sessions/config) to stay under the repo's file-size threshold; this
``__init__`` re-exports the full public surface so callers keep importing
from ``tests.e2e.mock_fixtures`` without caring about the internal layout.
"""

from tests.e2e.mock_fixtures.constants import APP_KEY_MY_APP, MANUAL_JOB_ID
from tests.e2e.mock_fixtures.manifests import (
    build_manifests,
    build_old_snapshot,
    wire_app_manifest_lookups,
    wire_owner_resolution,
)
from tests.e2e.mock_fixtures.scheduler import build_scheduler_jobs, wire_scheduler_trigger
from tests.e2e.mock_fixtures.sessions_config import build_session_list, wire_config, wire_session_telemetry
from tests.e2e.mock_fixtures.telemetry import (
    build_app_health_summaries,
    build_error_records,
    build_executions,
    build_global_summaries,
    build_job_telemetry,
    build_listener_telemetry,
    wire_app_health_summaries,
    wire_error_telemetry,
    wire_global_summary,
    wire_invocation_telemetry,
    wire_job_telemetry,
    wire_listener_telemetry,
)

__all__ = [
    "APP_KEY_MY_APP",
    "JOB_MY_APP_1_TOTAL_EXECUTIONS",
    "JOB_MY_APP_2_TOTAL_EXECUTIONS",
    "LISTENER_MY_APP_1_TOTAL_INVOCATIONS",
    "LISTENER_MY_APP_2_TOTAL_INVOCATIONS",
    "MANUAL_JOB_ID",
    "build_app_health_summaries",
    "build_error_records",
    "build_executions",
    "build_global_summaries",
    "build_job_telemetry",
    "build_listener_telemetry",
    "build_manifests",
    "build_old_snapshot",
    "build_scheduler_jobs",
    "build_session_list",
    "wire_app_health_summaries",
    "wire_app_manifest_lookups",
    "wire_config",
    "wire_error_telemetry",
    "wire_global_summary",
    "wire_invocation_telemetry",
    "wire_job_telemetry",
    "wire_listener_telemetry",
    "wire_owner_resolution",
    "wire_scheduler_trigger",
    "wire_session_telemetry",
]

# Derived constants for E2E test assertions — computed from the builder
# functions above so that changing a seed value automatically updates tests.
# This runs eagerly at package-import time (a deliberate inheritance from the
# original single-file module, not new behavior from the package split).

_listeners = build_listener_telemetry()
_jobs = build_job_telemetry()

LISTENER_MY_APP_1_TOTAL_INVOCATIONS: int = _listeners[APP_KEY_MY_APP][0].total_invocations
LISTENER_MY_APP_2_TOTAL_INVOCATIONS: int = _listeners[APP_KEY_MY_APP][1].total_invocations
JOB_MY_APP_1_TOTAL_EXECUTIONS: int = _jobs[APP_KEY_MY_APP][0].total_executions
JOB_MY_APP_2_TOTAL_EXECUTIONS: int = _jobs[APP_KEY_MY_APP][1].total_executions
