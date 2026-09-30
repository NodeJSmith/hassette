from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.apps import AppInstanceResponse
from hassette_wire.cli_format import CliFormat
from hassette_wire.enums import BackpressurePolicy, ExecutionMode, ExecutionStatus, ManifestStatus
from hassette_wire.literals import ErrorRateClass, HealthStatus, ListenerKind, SourceTier


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
    """How this execution was triggered (e.g., "manual" for a run-now request). None when not set."""
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
    handler_id: int
    """Listener or scheduled-job registration ID, interpreted according to ``kind``."""

    handler_name: str
    duration_ms: float | None = None
    error_type: str | None = None
    kind: Literal["handler", "job"]
    """Whether this is a handler invocation or a job execution."""


class JobSummary(BaseModel):
    """Per-job summary returned by ``get_job_summary()``.

    ``failed`` counts only ``'error'`` status; ``timed_out``, ``cancelled``, and ``skipped``
    are tracked separately.
    Invariant: ``successful + failed + cancelled + timed_out + skipped == total_executions``.
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
    predicate_description: str | None = None
    """Structural description of the job's scheduler predicate — ``repr()`` for composed
    predicate objects, the qualified name for a bare callable. ``None`` when unset."""
    human_description: str | None = None
    """Human-readable summary of the job's scheduler predicate, or ``None`` when unset."""
    total_executions: int
    successful: int
    failed: int
    cancelled: int = 0
    timed_out: int = 0
    skipped: int = 0
    """Number of executions where the scheduler predicate returned ``False`` and the handler
    did not run. Counted toward ``total_executions`` per the class invariant."""
    thread_leaked: int = 0
    """Number of executions whose sync worker thread outlived its timeout (see ``Execution.thread_leaked``).
    A non-zero value flags a job leaking worker threads.
    Mirrors the ``timed_out`` aggregate naming — the bare participle, not a ``_count`` suffix."""
    last_executed_at: float | None
    total_duration_ms: float
    avg_duration_ms: float
    group: str | None = None
    """Scheduler group name, persisted at registration."""
    schedule_status: str = "scheduled"
    """Current schedule status: ``scheduled``, ``waiting``, ``completed``, or ``manual``.
    Persisted at registration and every status transition; live enrichment overlays the
    current in-process value, so a DB-only degraded response still reflects the last
    persisted status."""
    schedule_status_reason: str | None = None
    """Optional diagnostic reason qualifying ``schedule_status``: ``legacy_unknown`` for rows
    backfilled by the schema migration before live re-registration establishes an exact
    status, or ``trigger_error`` for a ``completed`` job whose trigger raised while computing
    its next occurrence. ``None`` for a clean status with no override."""
    next_run: Annotated[float | None, CliFormat("relative_time")] = None
    """Unix epoch seconds of the next scheduled fire time (unjittered); live-only — always
    ``None`` in a DB-only response, and ``None`` for every status except ``scheduled`` with
    live timing available. A ``None`` value no longer implies the job is done; see
    ``schedule_status``/``schedule_status_reason`` for the reason timing is unavailable."""
    fire_at: float | None = None
    """Unix epoch seconds of the live job's dispatch time; live-only. Equals
    ``next_run`` when no jitter is configured."""
    jitter: float | None = None
    """Seconds of random jitter offset; live-only."""
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
    mode: ExecutionMode = ExecutionMode.SINGLE
    """Resolved overlap mode for this job. Persisted at registration."""
    suppressed_count: int = 0
    """Live count of re-fires suppressed by the guard (``single`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart."""
    dropped_count: int = 0
    """Live count of re-fires dropped due to queue cap (``queued`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart."""


class AppHealthResponse(BaseModel):
    """Health metrics for a single app instance."""

    error_rate: float
    error_rate_class: ErrorRateClass
    handler_avg_duration: Annotated[float, CliFormat("duration_ms")]
    job_avg_duration: Annotated[float, CliFormat("duration_ms")]
    last_activity_ts: Annotated[float | None, CliFormat("relative_time")]
    health_status: HealthStatus


class ListenerWithSummary(BaseModel):
    """Listener metrics enriched with human-readable handler summary."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    listener_id: int
    app_key: str
    instance_index: int = 0
    topic: str
    listener_kind: ListenerKind = "event"
    handler_method: str
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    avg_duration_ms: float = 0.0
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None
    total_duration_ms: float = 0.0
    predicate_description: str | None = None
    human_description: str | None = None
    debounce: float | None = None
    throttle: float | None = None
    once: int = 0
    priority: int = 0
    last_invoked_at: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None
    last_error_traceback: str | None = None
    timed_out: int = 0
    thread_leaked: int = 0
    source_location: str = ""
    registration_source: str | None = None
    handler_summary: str = ""
    source_tier: SourceTier = "app"
    immediate: int = 0
    duration: float | None = None
    target: str | None = None
    """What the listener is watching: an HA entity ID, or the topic's last segment for event listeners."""
    mode: ExecutionMode = ExecutionMode.SINGLE
    suppressed_count: int = 0
    dropped_count: int = 0
    backpressure_dropped_count: int = 0
    backpressure: BackpressurePolicy = BackpressurePolicy.BLOCK


class ActivityBucket(BaseModel):
    """A single time-window bucket for the sparkline chart."""

    ok: int
    """Number of successful invocations/executions in this bucket."""

    err: int
    """Number of error/timed-out invocations/executions in this bucket."""


class DashboardAppGridEntry(BaseModel):
    """Per-app health entry for the dashboard grid."""

    app_key: str
    status: ManifestStatus
    display_name: str
    instance_count: int = Field(
        default=0,
        description="Configured instances, including ones not currently tracked (never started, "
        "or independently stopped). Always len(instances).",
    )
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
    health_status: HealthStatus
    error_rate: float
    error_rate_class: ErrorRateClass
    activity_buckets: list[ActivityBucket] = Field(default_factory=list)
    """Per-app sparkline buckets (ok/err counts per time window)."""
    last_error_message: str | None = None
    last_error_type: str | None = None
    last_error_ts: float | None = None
    class_name: str = ""
    filename: str = ""
    enabled: bool = True
    auto_loaded: bool = False
    autostart: bool = True
    block_reason: str | None = None
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None
    error_traceback: str | None = None
    in_current_config: bool = Field(
        default=True,
        description="True if the app is present in the currently-loaded config; False for DB-only/removed apps.",
    )


class DashboardAppGridResponse(BaseModel):
    """Dashboard app grid with per-app health data."""

    apps: list[DashboardAppGridEntry]


class TelemetryStatusResponse(BaseModel):
    """Health check response for the telemetry database."""

    degraded: bool
    dropped_overflow: int = 0
    dropped_exhausted: int = 0
    dropped_shutdown: int = 0
    dropped_filtered: int = 0
    error_handler_failures: int = 0


class JobTriggerResponse(BaseModel):
    """Response for POST /api/scheduler/jobs/{job_id}/trigger — manual job submission.

    Separate from ``ActionResponse`` (which has ``app_key``/``action`` but no ``job_id``) —
    the trigger response identifies the job, not an app action. ``status`` is always
    ``"accepted"`` for a live registration (the endpoint returns 409 instead of this model
    when the job has no live registration) — overlap-policy suppression or dropping happens
    asynchronously and is not previewed in this response.
    """

    status: Literal["accepted"] = "accepted"
    job_id: int
    job_name: str
