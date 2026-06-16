"""Pydantic models for TelemetryQueryService DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

Separation rationale
--------------------
- ``telemetry_models.py`` — historical/aggregated data from the database (this module)
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from typing import Literal, NamedTuple

from pydantic import BaseModel

from hassette.types.types import LOG_LEVEL_TYPE, ExecutionStatus, SourceTier

_BlockingTier = Literal["watchdog", "monkeypatch"]


class AppLastError(NamedTuple):
    error_message: str
    error_type: str | None
    timestamp: float


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

    @property
    def error_rate(self) -> float:
        """Combined handler + job failure rate as a percentage (0.0-100.0)."""
        total = self.total_invocations + self.total_executions
        if total == 0:
            return 0.0
        failures = self.total_errors + self.total_timed_out + self.total_job_errors + self.total_job_timed_out
        return failures / total * 100

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
    mode: str = "single"
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    timed_out: int = 0
    total_duration_ms: float
    avg_duration_ms: float
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None
    last_invoked_at: float | None
    last_error_type: str | None
    last_error_message: str | None
    last_error_traceback: str | None = None


class Execution(BaseModel):
    """Unified execution record returned by queries against the ``executions`` table.

    Replaces the split ``HandlerInvocation`` / ``JobExecution`` models.
    ``kind`` discriminates between handler invocations and job executions.
    Handler-only fields (``trigger_context_id``, ``trigger_origin``) default to
    ``None`` for job executions.
    """

    kind: Literal["handler", "job"]
    """Discriminator: 'handler' for bus invocations, 'job' for scheduled-job executions."""

    listener_id: int | None = None
    """The owning listener row id. Set when kind='handler', None for job executions."""
    job_id: int | None = None
    """The owning scheduled-job row id. Set when kind='job', None for handler invocations."""

    execution_start_ts: float
    duration_ms: float
    status: ExecutionStatus
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None
    execution_id: str | None = None
    """UUID string identifying the specific execution instance. None when not populated.

    UUIDv7 for new executions (embeds timestamp); UUIDv4 for historical executions.
    """
    trigger_context_id: str | None = None
    """event_id from the triggering event payload. None for job executions and non-event-triggered invocations."""
    trigger_origin: str | None = None
    """Origin of the triggering event (e.g., 'LOCAL', 'REMOTE', 'HASSETTE'). None for job executions."""
    trigger_mode: str | None = None
    """Trigger mode string (e.g., 'immediate', 'debounced'). None when not set."""
    retry_count: int = 0
    """Number of retry attempts before this execution. 0 for first attempts."""
    attempt_number: int = 1
    """Ordinal attempt number (1-based). 1 for first attempt."""
    args_json: str = "[]"
    """JSON-encoded positional arguments for job executions. '[]' for handler invocations."""
    kwargs_json: str = "{}"
    """JSON-encoded keyword arguments for job executions. '{}' for handler invocations."""
    thread_leaked: bool = False
    """True when the execution timed out and the sync worker thread was still alive after the timeout.

    Subject to a small race window: if the worker finishes between the timeout cancellation and the
    liveness check, this field reads False even though the thread outlived the asyncio deadline.
    This is a false-negative (undercounting), not a false-positive. Treat as a lower bound.
    """


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
    name_auto: bool = False
    """True when the job name was auto-generated from the callable and trigger ID."""
    last_error_message: str | None = None
    """Most recent error message within the query window, or None."""
    last_error_type: str | None = None
    """Most recent error exception type within the query window, or None."""
    last_error_ts: float | None = None
    """Unix epoch of the most recent error within the query window, or None."""
    last_error_traceback: str | None = None
    """Traceback from the most recent error within the query window, or None."""
    min_duration_ms: float | None = None
    """Minimum execution duration in milliseconds. None means no executions; 0.0 means executed in under 1ms."""
    max_duration_ms: float | None = None
    """Maximum execution duration in milliseconds. None means no executions; 0.0 means executed in under 1ms."""


class ListenerGlobalStats(BaseModel):
    """Listener aggregate stats within ``GlobalSummary``."""

    total_listeners: int
    invoked_listeners: int
    total_invocations: int
    total_errors: int
    total_timed_out: int = 0
    total_di_failures: int
    avg_duration_ms: float | None


class JobGlobalStats(BaseModel):
    """Job aggregate stats within ``GlobalSummary``."""

    total_jobs: int
    executed_jobs: int
    total_executions: int
    total_errors: int
    total_timed_out: int = 0
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
    source_location: str | None = None
    """Source file location of the handler (e.g. 'my_app.py:42')."""


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
    source_location: str | None = None
    """Source file location of the job handler (e.g. 'my_app.py:99')."""


class ActivityFeedEntry(BaseModel):
    """A single activity entry for the cross-app recent activity feed."""

    row_id: str
    """Stable unique identifier for this entry.

    Carries the ``execution_id`` UUID when present. Rows that predate the
    ``execution_id`` column fall back to ``'h-'`` (handler) or ``'j-'`` (job)
    prefixing the SQLite rowid. The type is always ``str``.
    """

    status: ExecutionStatus
    """Handler or job execution status."""

    timestamp: float
    """Unix epoch float for when the invocation/execution started."""

    app_key: str
    handler_name: str
    duration_ms: float | None = None
    error_type: str | None = None
    kind: Literal["handler", "job"]
    """Whether this is a handler invocation or a job execution."""


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


class LogRecord(BaseModel):
    """Single log record returned by ``get_log_records()`` and ``get_log_records_by_execution()``."""

    id: int
    seq: int
    timestamp: float
    level: LOG_LEVEL_TYPE
    logger_name: str
    func_name: str | None = None
    lineno: int | None = None
    message: str
    exc_info: str | None = None
    app_key: str | None = None
    instance_name: str | None = None
    instance_index: int | None = None
    execution_id: str | None = None
    """UUID string identifying the execution that produced this log record. None for framework logs.

    UUIDv7 for new executions (embeds timestamp); UUIDv4 for historical executions."""
    source_tier: SourceTier | None = None
    """``'app'`` for user automation logs, ``'framework'`` for internal service logs."""


class BlockingEvent(BaseModel):
    """A single blocking event row from the ``blocking_events`` table.

    Written by ``TelemetryRepository.insert_blocking_event`` for every detected
    Tier 1 (watchdog) or Tier 2 (monkeypatch) event. ``app_key`` is nullable so
    unresolved (framework-attributed) owners are recorded, not dropped.
    """

    session_id: int | None
    """Session that was running when the event was detected. None when no session exists yet."""

    app_key: str | None
    """App key of the owner, or ``None`` for unresolved/framework stalls."""

    instance_name: str | None
    instance_index: int | None

    execution_id: str | None
    """UUIDv7 execution that froze the loop. None when no marker was live (Tier 2 off-handler)."""

    tier: _BlockingTier
    """``'watchdog'`` for Tier 1 events; ``'monkeypatch'`` for Tier 2 events."""

    primitive: str | None
    """Blocking primitive name (Tier 2 only, e.g. ``'time.sleep'``). None for Tier 1."""

    source_location: str | None
    """Call-site location string (Tier 2) or loop-thread stack text (Tier 1, when captured)."""

    stall_duration_ms: float | None
    """Stall duration in milliseconds (Tier 1 only). None for Tier 2 events."""

    detected_ts: float
    """Unix epoch seconds when the event was detected (``time.time()``)."""

    source_tier: SourceTier
    """``'app'`` when ``app_key`` is set; ``'framework'`` for unresolved owners."""
