"""Pydantic models for unified execution telemetry DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

Separation rationale
--------------------
- ``listener_models.py`` — per-listener summaries, stats, and error records
- ``execution_models.py`` — unified execution records and activity feed (this module)
- ``job_models.py`` — per-job summaries, stats, and error records
- ``summary_models.py`` — app-health and global aggregates
- ``log_models.py`` — log records and blocking events
- ``domain_models.py`` — live state snapshots and WS event payloads
"""

from typing import Literal, NamedTuple

from pydantic import BaseModel

from hassette.types.types import ExecutionStatus, SourceTier


class AppLastError(NamedTuple):
    error_message: str
    error_type: str | None
    timestamp: float


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
