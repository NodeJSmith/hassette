from typing import Annotated

from pydantic import BaseModel, ConfigDict

from hassette_wire.apps import AppSummary
from hassette_wire.cli_format import CliFormat
from hassette_wire.enums import (
    BackpressurePolicy,
    ExecutionMode,
    OpenBackpressurePolicy,
    OpenExecutionMode,
    OpenExecutionStatus,
    OpenScheduleStatus,
    OpenScheduleStatusReason,
)
from hassette_wire.literals import (
    OpenAcceptedStatus,
    OpenErrorRateClass,
    OpenExecutionKind,
    OpenHealthStatus,
    OpenListenerKind,
    SourceTier,
)

WINDOWED_ACTIVITY_PARTS: frozenset[str] = frozenset({"activity_buckets", "last_error"})
"""``AppActivity`` parts the server computes only for a request with a ``since``; ``None`` in every row
otherwise. Mirrored in ``frontend/src/utils/app-data.ts``; ``tests/unit/test_frontend_windowed_parts_parity.py``
fails when the two drift."""


def requested_activity_parts(*, windowed: bool) -> list[str]:
    """``AppActivity`` parts the server computes: every part when ``windowed``, else the unwindowed ones."""
    return [name for name in AppActivity.model_fields if windowed or name not in WINDOWED_ACTIVITY_PARTS]


class Execution(BaseModel):
    """One run of a handler or scheduled job.

    ``kind`` says which. Handler-only fields (``trigger_context_id``, ``trigger_origin``) are
    ``None`` for job executions.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    kind: OpenExecutionKind
    """Discriminator: 'handler' for bus invocations, 'job' for scheduled-job executions."""

    listener_id: int | None = None
    """The owning listener row id. Set when kind='handler', None for job executions."""
    job_id: int | None = None
    """The owning scheduled-job row id. Set when kind='job', None for handler invocations."""

    execution_start_ts: float
    duration_ms: float
    status: OpenExecutionStatus
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None
    execution_id: str | None = None
    """UUID string identifying the specific execution instance. None when not populated.

    UUIDv7 for new executions (embeds timestamp); UUIDv4 for historical executions.
    """
    trigger_context_id: str | None = None
    """event_id from the triggering event payload. None for job executions, synthetic immediate-fire
    invocations, and handler rows recorded because the listener's predicate raised."""
    trigger_origin: str | None = None
    """Origin of the triggering event (e.g., 'LOCAL', 'REMOTE', 'HASSETTE'; 'HASSETTE_SYNTHETIC' for
    immediate-fire synthetic invocations). None for job executions and for handler rows recorded because
    the listener's predicate raised."""
    trigger_mode: str | None = None
    """How this execution was triggered (e.g., "manual" for a run-now request). None when not set."""
    retry_count: int = 0
    """Reserved for future retry tracking; currently always 0."""
    attempt_number: int = 1
    """Reserved for future retry tracking; currently always 1."""
    args_json: str = "[]"
    """Reserved; not currently populated, so always '[]'. A job's registered positional arguments are
    on ``JobSummary.args_json``."""
    kwargs_json: str = "{}"
    """Reserved; not currently populated, so always '{}'. A job's registered keyword arguments are
    on ``JobSummary.kwargs_json``."""
    thread_leaked: bool = False
    """True when the execution timed out and the sync worker thread was still alive after the timeout.

    Subject to a small race window: if the worker finishes between the timeout cancellation and the
    liveness check, this field reads False even though the thread outlived the asyncio deadline.
    This is a false-negative (undercounting), not a false-positive. Treat as a lower bound.
    """


class ActivityFeedEntry(BaseModel):
    """A single activity entry for the cross-app recent activity feed."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    row_id: str
    """Stable unique identifier for this entry.

    Carries the ``execution_id`` UUID when present. Rows that predate the
    ``execution_id`` column fall back to ``'h-'`` (handler) or ``'j-'`` (job)
    prefixing the SQLite rowid. The type is always ``str``.
    """

    status: OpenExecutionStatus
    """Handler or job execution status."""

    timestamp: float
    """Unix epoch float for when the invocation/execution started."""

    app_key: str
    handler_id: int
    """Listener or scheduled-job registration ID, interpreted according to ``kind``."""

    handler_name: str
    duration_ms: float | None = None
    error_type: str | None = None
    kind: OpenExecutionKind
    """Whether this is a handler invocation or a job execution."""


class JobSummary(BaseModel):
    """One scheduled job's registration and its execution totals.

    ``failed`` counts only ``'error'`` status; ``timed_out``, ``cancelled``, and ``skipped``
    are tracked separately.
    Invariant: ``successful + failed + cancelled + timed_out + skipped == total_executions``.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

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
    schedule_status: OpenScheduleStatus
    """Whether the job will run again on its own: its live status while it is registered with the running
    scheduler, otherwise the last status the server recorded for it."""
    schedule_status_reason: OpenScheduleStatusReason | None = None
    """Qualifies ``schedule_status`` when the status alone does not explain the job's state.
    ``None`` for a clean status with no override."""
    next_run: Annotated[float | None, CliFormat("relative_time")] = None
    """Unix epoch seconds of the next scheduled fire time (unjittered). ``None`` when:

    - the job is not registered with the running scheduler,
    - the server could not read live scheduler state, or
    - ``schedule_status`` is anything other than ``scheduled``.

    ``None`` does not mean the job is done; ``schedule_status`` and ``schedule_status_reason`` say why."""
    fire_at: float | None = None
    """Unix epoch seconds of the live job's dispatch time; live-only. Equals
    ``next_run`` when no jitter is configured."""
    jitter: float | None = None
    """Configured maximum jitter in seconds, not the offset sampled for this occurrence;
    live-only. The applied offset is ``fire_at - next_run``."""
    last_error_message: str | None = None
    """Message of the most recent error or timeout within the query window, or None."""
    last_error_type: str | None = None
    """Exception type of the most recent error or timeout within the query window, or None."""
    last_error_ts: float | None = None
    """Unix epoch of the most recent error or timeout within the query window, or None."""
    last_error_traceback: str | None = None
    """Traceback from the most recent error or timeout within the query window. None when there is none,
    or when that row recorded no traceback (timeouts never do)."""
    min_duration_ms: float | None = None
    """Minimum duration in milliseconds across non-skipped executions. None means no non-skipped executions."""
    max_duration_ms: float | None = None
    """Maximum duration in milliseconds across non-skipped executions. None means no non-skipped executions."""
    mode: OpenExecutionMode = ExecutionMode.SINGLE
    """Resolved overlap mode for this job. Persisted at registration."""
    suppressed_count: int = 0
    """Live count of re-fires suppressed by the guard (``single`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart. Reads 0 when the job has no live match or the
    live registry is unavailable, so 0 does not prove none occurred."""
    dropped_count: int = 0
    """Live count of re-fires dropped due to queue cap (``queued`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart. Reads 0 when the job has no live match or the
    live registry is unavailable, so 0 does not prove none occurred."""


class AppHealth(BaseModel):
    """Health of an app over a time window: one app instance, or all instances of an app.

    Computed over every execution in the window, including those of handlers and jobs removed since.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    error_rate: float
    """Failed (error or timed out) handler and job executions as a percentage of all of them."""
    error_rate_class: OpenErrorRateClass
    health_status: OpenHealthStatus
    last_activity_ts: Annotated[float | None, CliFormat("relative_time")]
    """Start of the latest handler or job execution, or null when nothing ran."""
    handler_avg_duration_ms: Annotated[float | None, CliFormat("duration_ms")]
    """Mean handler execution duration, or null when no handler ran."""
    job_avg_duration_ms: Annotated[float | None, CliFormat("duration_ms")]
    """Mean job execution duration excluding skipped runs; null when no job ran or every job run was skipped."""


class ListenerSummary(BaseModel):
    """One bus listener's registration and its invocation totals."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    listener_id: int
    app_key: str
    instance_index: int = 0
    topic: str
    listener_kind: OpenListenerKind = "event"
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
    mode: OpenExecutionMode = ExecutionMode.SINGLE
    suppressed_count: int = 0
    dropped_count: int = 0
    backpressure_dropped_count: int = 0
    backpressure: OpenBackpressurePolicy = BackpressurePolicy.BLOCK


class ActivityBucket(BaseModel):
    """A single time-window bucket for the sparkline chart."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    ok: int
    """Number of successful invocations/executions in this bucket."""

    err: int
    """Number of error/timed-out invocations/executions in this bucket."""


class AppActivityStats(BaseModel):
    """An app's listener and job counts, run totals and health over the grid's window."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    handler_count: int
    job_count: int
    total_invocations: int
    total_errors: int
    total_timed_out: int
    total_executions: int
    total_job_errors: int
    total_job_timed_out: int
    health: AppHealth


class LastError(BaseModel):
    """The most recent handler or job error for an app in the grid's window."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    error_message: str
    error_type: str | None = None
    ts: float
    """When the failing execution started (Unix seconds)."""


class LastErrorResult(BaseModel):
    """The outcome of the last-error lookup for one app."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    error: LastError | None
    """The most recent error in the window. ``None`` means the lookup ran and found no error."""


class AppActivity(BaseModel):
    """How an app is doing over the grid's time window (``AppGridResponse.since``).

    Each part comes from its own all-apps enrichment query and is ``None`` exactly when that query
    failed or did not run: ``activity_buckets`` and ``last_error`` only run for a window, so they are
    ``None`` when ``since`` is ``None``. A computed part is never ``None``. The parts are read
    separately, so they need not agree with each other (e.g. error totals against ``last_error``).
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    stats: AppActivityStats | None
    """Counts, run totals and health. ``None`` when the summary query failed."""
    activity_buckets: list[ActivityBucket] | None
    """Per-app sparkline: equal-width ok/err buckets from ``since`` to now, oldest first; empty when the app
    had no executions in the window. ``None`` when the bucket query failed or the request had no ``since``."""
    last_error: LastErrorResult | None
    """The last-error lookup. ``None`` when it failed or the request had no ``since``."""
    blocking_event_count: int | None
    """Attributed blocking-IO events for this app in the requested window. ``None`` when the count query
    failed."""


class AppGridEntry(BaseModel):
    """One Apps grid row: an app joined with its activity, in a single server-side query."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    app: AppSummary
    """What the app is: identity, lifecycle status and instances."""

    activity: AppActivity
    """What the app did over the grid's window; each part is ``None`` when it wasn't computed."""


class AppGridResponse(BaseModel):
    """The Apps grid: every app with its activity over ``since``."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    apps: list[AppGridEntry]
    since: float | None = None
    """The window start the activity covers, echoed from the request. ``None`` means all-time totals,
    with ``activity_buckets`` and ``last_error`` not computed (``None`` in every row)."""


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

    status: OpenAcceptedStatus = "accepted"
    job_id: int
    job_name: str
