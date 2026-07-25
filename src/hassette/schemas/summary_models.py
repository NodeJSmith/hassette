"""Pydantic models for app-health and global telemetry summary DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

Separation rationale
--------------------
- ``listener_models.py`` — per-listener summaries, stats, and error records
- ``execution_models.py`` — unified execution records and activity feed
- ``job_models.py`` — per-job summaries, stats, and error records
- ``summary_models.py`` — app-health and global aggregates (this module)
- ``log_models.py`` — log records and blocking events
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from pydantic import BaseModel

from hassette.schemas.job_models import JobGlobalStats
from hassette.schemas.listener_models import ListenerGlobalStats


class AppHealthSummary(BaseModel):
    """Per-app health summary returned by ``get_all_app_summaries()``."""

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


class GlobalSummary(BaseModel):
    """Aggregate telemetry summary returned by ``get_global_summary()``."""

    listeners: ListenerGlobalStats
    jobs: JobGlobalStats


class SessionRecord(BaseModel):
    """Single session record returned by ``get_session_list()``."""

    id: int
    started_at: float
    stopped_at: float | None
    status: str
    error_type: str | None
    error_message: str | None
    duration_seconds: float | None
    dropped_overflow: int = 0
    dropped_exhausted: int = 0
    dropped_shutdown: int = 0


class SessionSummary(BaseModel):
    """Current-session summary returned by ``get_current_session_summary()``."""

    started_at: float
    last_heartbeat_at: float
    total_invocations: int
    invocation_errors: int
    total_executions: int
    execution_errors: int
