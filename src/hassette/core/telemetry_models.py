"""Pydantic models for TelemetryQueryService DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

Separation rationale
--------------------
- ``telemetry_models.py`` — historical/aggregated data from the database (this module)
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from typing import Literal

from pydantic import BaseModel

from hassette.types.types import SourceTier


class AppHealthSummary(BaseModel):
    """Per-app health summary returned by ``get_all_app_summaries()``."""

    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_executions: int
    total_job_errors: int
    avg_duration_ms: float
    last_activity_ts: float | None

    @property
    def error_rate(self) -> float:
        """Combined handler + job error rate as a percentage (0.0-100.0)."""
        total = self.total_invocations + self.total_executions
        if total == 0:
            return 0.0
        errors = self.total_errors + self.total_job_errors
        return errors / total * 100

    @property
    def success_rate(self) -> float:
        """Combined handler + job success rate as a percentage (0.0-100.0)."""
        total = self.total_invocations + self.total_executions
        if total == 0:
            return 100.0
        return 100.0 - self.error_rate


class ListenerSummary(BaseModel):
    """Per-listener summary returned by ``get_listener_summary()``.

    ``failed`` counts only ``'error'`` status; ``timed_out`` is tracked separately.
    Invariant: ``successful + failed + cancelled + timed_out == total_invocations``.
    """

    listener_id: int
    app_key: str
    instance_index: int
    handler_method: str
    topic: str
    debounce: float | None
    throttle: float | None
    once: int
    priority: int
    predicate_description: str | None
    human_description: str | None
    source_location: str
    registration_source: str | None
    source_tier: SourceTier = "app"
    immediate: int = 0
    duration: float | None = None
    entity_id: str | None = None
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    timed_out: int = 0
    total_duration_ms: float
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    last_invoked_at: float | None
    last_error_type: str | None
    last_error_message: str | None


class HandlerInvocation(BaseModel):
    """Single invocation record returned by ``get_handler_invocations()``."""

    execution_start_ts: float
    duration_ms: float
    status: str
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None


class JobSummary(BaseModel):
    """Per-job summary returned by ``get_job_summary()``.

    ``failed`` counts only ``'error'`` status; ``timed_out`` is tracked separately.
    Invariant: ``successful + failed + timed_out == total_executions``.
    """

    job_id: int
    app_key: str
    instance_index: int
    job_name: str
    handler_method: str
    trigger_type: str | None
    trigger_label: str = ""
    trigger_detail: str | None = None
    args_json: str
    kwargs_json: str
    source_location: str
    registration_source: str | None
    source_tier: SourceTier = "app"
    total_executions: int
    successful: int
    failed: int
    timed_out: int = 0
    last_executed_at: float | None
    total_duration_ms: float
    avg_duration_ms: float
    group: str | None = None
    """Scheduler group name, persisted at registration."""
    next_run: float | None = None
    """Unix epoch seconds of the next scheduled fire time (unjittered); sourced from live heap."""
    fire_at: float | None = None
    """Unix epoch seconds of actual dispatch time when jitter applied; sourced from live heap."""
    jitter: float | None = None
    """Seconds of random jitter offset; sourced from live heap."""
    cancelled: bool = False
    """True when the job is cancelled; derived solely from ``cancelled_at IS NOT NULL`` in the DB."""


class JobExecution(BaseModel):
    """Single execution record returned by ``get_job_executions()``."""

    execution_start_ts: float
    duration_ms: float
    status: str
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None


class ListenerGlobalStats(BaseModel):
    """Listener aggregate stats within ``GlobalSummary``."""

    total_listeners: int
    invoked_listeners: int
    total_invocations: int
    total_errors: int
    total_di_failures: int
    avg_duration_ms: float | None


class JobGlobalStats(BaseModel):
    """Job aggregate stats within ``GlobalSummary``."""

    total_jobs: int
    executed_jobs: int
    total_executions: int
    total_errors: int
    avg_duration_ms: float = 0.0


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
    dropped_no_session: int = 0
    dropped_shutdown: int = 0


class SessionSummary(BaseModel):
    """Current-session summary returned by ``get_current_session_summary()``."""

    started_at: float
    last_heartbeat_at: float
    total_invocations: int
    invocation_errors: int
    total_executions: int
    execution_errors: int


class HandlerErrorRecord(BaseModel):
    """Handler error returned by ``get_recent_errors()``."""

    kind: Literal["handler"] = "handler"
    listener_id: int | None
    app_key: str | None
    handler_method: str | None
    topic: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None


class JobErrorRecord(BaseModel):
    """Job error returned by ``get_recent_errors()``."""

    kind: Literal["job"] = "job"
    job_id: int | None
    app_key: str | None
    job_name: str | None
    handler_method: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None


class SlowHandlerRecord(BaseModel):
    """Slow handler invocation returned by ``get_slow_handlers()``.

    ``app_key``, ``handler_method``, and ``topic`` are nullable because
    ``get_slow_handlers`` uses a LEFT JOIN.  Orphaned invocations (whose
    listener row was deleted) are still returned with ``None`` for these fields.
    """

    app_key: str | None
    handler_method: str | None
    topic: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier
