"""Pydantic models for app-health and global telemetry summary DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For app-registry snapshots, see ``hassette.schemas.app_snapshots``. For the live
system-status snapshot, served models, and WS payloads, see ``hassette_wire``.

See ``schemas/__init__.py`` for the domain-file map.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict

from hassette.schemas.job_models import JobGlobalStats
from hassette.schemas.listener_models import ListenerGlobalStats


class AppHealthAggregates(BaseModel):
    """Handler and job execution aggregates for one app over a time window.

    The single input to app-health computation, for both scopes: one app instance
    (``get_app_health_aggregates()``) and all instances of an app (``get_all_app_summaries()``).
    Counts include executions of handlers and jobs removed since they ran. An average is
    ``None`` when nothing of its kind ran; the job average excludes skipped executions, so it is
    also ``None`` when every job run in the window was skipped.
    """

    model_config = ConfigDict(frozen=True)

    total_invocations: int
    handler_errors: int
    handler_timed_out: int
    handler_avg_duration_ms: float | None
    total_executions: int
    job_errors: int
    job_timed_out: int
    job_avg_duration_ms: float | None
    last_activity_ts: float | None

    @classmethod
    def empty(cls) -> Self:
        """Aggregates for a window in which nothing ran: zero counts, no averages."""
        return cls(
            total_invocations=0,
            handler_errors=0,
            handler_timed_out=0,
            handler_avg_duration_ms=None,
            total_executions=0,
            job_errors=0,
            job_timed_out=0,
            job_avg_duration_ms=None,
            last_activity_ts=None,
        )


class AppHealthSummary(BaseModel):
    """Per-app health summary returned by ``get_all_app_summaries()``.

    ``handler_count``/``job_count`` count currently registered handlers and jobs only, while
    ``aggregates`` covers every execution in the window.
    """

    handler_count: int
    job_count: int
    aggregates: AppHealthAggregates


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
