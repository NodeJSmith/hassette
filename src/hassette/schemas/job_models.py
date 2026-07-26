"""Pydantic models for job (scheduled task) telemetry DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

See ``schemas/__init__.py`` for the domain-file map.
"""

from typing import Literal

from pydantic import BaseModel

from hassette.types.enums import DEFAULT_OVERLAP_MODE, ExecutionMode
from hassette.types.types import SourceTier


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
    """Python ``repr()`` of the job's scheduler predicate, or ``None`` when unset."""
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
    Aggregated from the ``executions`` table; a non-zero value flags a job leaking worker threads.
    Mirrors the ``timed_out`` aggregate naming — the bare participle, not a ``_count`` suffix."""
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
    mode: ExecutionMode = DEFAULT_OVERLAP_MODE
    """Resolved overlap mode for this job. Persisted at registration; sourced from the DB column
    ``scheduled_jobs.mode``."""
    suppressed_count: int = 0
    """Live count of re-fires suppressed by the guard (``single`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart."""
    dropped_count: int = 0
    """Live count of re-fires dropped due to queue cap (``queued`` mode). Not persisted by design — read
    live from the in-process guard and reset to 0 on restart."""


class JobGlobalStats(BaseModel):
    """Job aggregate stats within ``GlobalSummary``."""

    total_jobs: int
    executed_jobs: int
    total_executions: int
    total_errors: int
    total_timed_out: int = 0
    avg_duration_ms: float = 0.0


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
