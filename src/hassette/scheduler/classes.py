import itertools
import typing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from logging import getLogger
from typing import Any

from croniter import croniter
from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.types.types import SourceTier

if typing.TYPE_CHECKING:
    from hassette.types import JobCallable, TriggerProtocol


LOGGER = getLogger(__name__)

# next_id() is only called at job creation time on the event loop thread.
# itertools.count.__next__ is C-atomic. No lock needed unless the project targets
# free-threaded CPython (PEP 703), which would require a broader concurrency audit.
seq = itertools.count(1)


def next_id() -> int:
    return next(seq)


class CronTrigger:
    """Internal cron-expression trigger backing ``Daily`` and ``Cron`` from ``hassette.scheduler.triggers``.

    Not part of the public API — use ``Daily`` or ``Cron`` from ``hassette.scheduler.triggers`` instead.
    """

    def __init__(self, cron_expression: str, start: ZonedDateTime | None = None):
        self.cron_expression = cron_expression
        self.start = start
        # Validate expression eagerly at construction time
        base = start or date_utils.now()
        croniter(cron_expression, base.py_datetime(), ret_type=datetime)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CronTrigger):
            return NotImplemented
        return self.cron_expression == other.cron_expression

    def __hash__(self) -> int:
        return hash(self.cron_expression)

    def __str__(self) -> str:
        return f"cron:{self.cron_expression}"

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first cron-grid-aligned run time at or after current_time."""
        # Use start as the croniter anchor, but always snap to the cron grid.
        # This finds the first cron-aligned time at or after start (or current_time if no start).
        anchor = self.start or current_time
        reference = self.start if (self.start is not None and self.start > current_time) else current_time
        return self._next_after(anchor, reference)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next cron-grid-aligned run time after previous_run that is later than current_time."""
        return self._next_after(previous_run, current_time)

    def _next_after(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        cron = croniter(self.cron_expression, anchor.py_datetime(), ret_type=datetime)
        # Normalise current_time to UTC so the ``next_time > current_dt`` comparison below is
        # unambiguous around DST transitions. During fall-back, ``current_time`` may carry
        # fold=0 (pre-transition, CDT) while croniter returns fold=1 wall-clock values (CST).
        # Without UTC normalisation, the CST occurrence appears UTC-earlier than the CDT
        # anchor and the loop skips the ambiguous slot entirely.
        current_dt_utc = current_time.py_datetime().astimezone(UTC)
        ambiguous_ticks_skipped = 0
        # Bounded iteration — avoids O(N) spin for sub-second crons after long downtime.
        # 10,000 iterations covers ~2.7 hours of per-second crons, which is generous.
        max_iterations = 10_000
        for _ in range(max_iterations):
            next_time = cron.get_next()
            if next_time.astimezone(UTC) > current_dt_utc:
                result = self._dst_safe_from_dt(next_time)
                # Log when DST disambiguation is actually relevant: either the returned
                # tick itself is ambiguous (fold=1 was meaningful), or we traversed
                # ambiguous ticks on the way here. Logs the dispatched result (post-
                # disambiguation) to avoid printing a wall-clock string that differs from
                # the instant actually scheduled.
                returned_is_ambiguous = self._is_fall_back_ambiguous(next_time)
                if ambiguous_ticks_skipped or returned_is_ambiguous:
                    LOGGER.info(
                        "CronTrigger(%s): DST fall-back disambiguation — %d ambiguous tick(s) "
                        "traversed; returning %s (fold=1, post-transition)",
                        self.cron_expression,
                        ambiguous_ticks_skipped + (1 if returned_is_ambiguous else 0),
                        result,
                    )
                return result
            # Only count ticks we actually skipped past — the tick that exits the loop is
            # handled above.
            if self._is_fall_back_ambiguous(next_time):
                ambiguous_ticks_skipped += 1
        # Too many iterations — skip ahead from current time.
        # Re-anchor croniter in the *original* timezone so cron expressions like
        # "0 9 * * *" still fire at 09:00 local time, not 09:00 UTC.
        LOGGER.warning(
            "CronTrigger(%s) exceeded %d iterations catching up, skipping ahead from current_time",
            self.cron_expression,
            max_iterations,
        )
        skip_ahead_dt = current_time.py_datetime()
        cron = croniter(self.cron_expression, skip_ahead_dt, ret_type=datetime)
        next_time = cron.get_next()
        return self._dst_safe_from_dt(next_time)

    @staticmethod
    def _is_fall_back_ambiguous(dt: datetime) -> bool:
        """Return True when ``dt``'s wall-clock time occurs twice (fall-back ambiguity)."""
        return dt.replace(fold=0).astimezone(UTC) != dt.replace(fold=1).astimezone(UTC)

    @staticmethod
    def _dst_safe_from_dt(dt: datetime) -> ZonedDateTime:
        """Convert a croniter-produced datetime to ZonedDateTime with DST disambiguation.

        Uses ``fold=1`` (post-transition / "later" occurrence) to handle:
        - **Fall-back (fold/repeated time):** prefers the second (post-transition) occurrence.
          The caller is responsible for logging when ambiguity is encountered (see
          ``_next_after``), which emits a single summary per call instead of per-tick spam.
        - **Spring-forward (gap/skipped time):** croniter already advances past the gap, so
          ``fold=1`` and ``fold=0`` produce the same result for non-gap times.

        Args:
            dt: A timezone-aware datetime produced by ``croniter.get_next()`` with a
                ``ZoneInfo``-backed tzinfo.

        Returns:
            A ``ZonedDateTime`` with DST disambiguation applied.
        """
        return ZonedDateTime.from_py_datetime(dt.replace(fold=1))


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    sort_index: tuple[int, int] = field(init=False, repr=False)
    """Tuple of (next_run timestamp with nanoseconds, job_id) for ordering in a priority queue."""

    owner_id: str = field(compare=False)
    """Unique string identifier for the owner of the job, e.g., a component or integration name."""

    next_run: ZonedDateTime = field(compare=False)
    """Unjittered logical fire time — used as `previous_run` in subsequent trigger calls."""

    fire_at: ZonedDateTime = field(init=False, compare=False)
    """Actual dispatch time, including any jitter offset.

    Equals ``next_run`` when no jitter is configured. Set by
    ``SchedulerService._apply_jitter_to_heap()`` at enqueue time when jitter > 0.
    The pop loop in ``_ScheduledJobQueue.pop_due_and_peek_next`` compares against
    ``fire_at`` (not ``next_run``) to decide when to dispatch.
    """

    job: "JobCallable" = field(compare=False)
    """The callable to execute when the job runs."""

    app_key: str = field(default="", compare=False)
    """Configuration-level app key for DB registration (e.g., 'my_app'). Empty for non-App owners."""

    instance_index: int = field(default=0, compare=False)
    """App instance index for DB registration. 0 for non-App owners."""

    trigger: "TriggerProtocol | None" = field(compare=False, default=None)
    """The trigger that determines the job's schedule."""

    group: str | None = field(default=None, compare=False)
    """Optional group name for grouping related jobs. Included in deduplication comparison."""

    jitter: float | None = field(default=None, compare=False)
    """Seconds of random offset applied at enqueue time by ``SchedulerService._apply_jitter_to_heap()``.

    Does not affect ``next_run`` (unjittered logical fire time). See the ``fire_at`` field on
    ``ScheduledJob`` for the actual dispatch time after jitter is applied.
    """

    name: str = field(default="", compare=False)
    """Optional name for the job for easier identification."""

    cancelled: bool = field(default=False, compare=False)
    """Flag indicating whether the job has been cancelled."""

    args: tuple[Any, ...] = field(default_factory=tuple, compare=False)
    """Positional arguments to pass to the job callable."""

    kwargs: dict[str, Any] = field(default_factory=dict, compare=False)
    """Keyword arguments to pass to the job callable."""

    job_id: int = field(default_factory=next_id, init=False, compare=False)
    """Unique identifier for the job instance."""

    db_id: int | None = field(default=None, compare=False)
    """Database row ID for this job. Set by the executor after persistence; None until then."""

    source_location: str = field(default="", compare=False)
    """Captured source location (file:line) of the user code that scheduled this job."""

    registration_source: str = field(default="", compare=False)
    """Captured source code snippet of the scheduling call."""

    source_tier: SourceTier = field(default="app", compare=False)
    """Whether this job originates from a user app or the framework itself."""

    def __hash__(self) -> int:
        # Hashing on job_id is safe because @dataclass(order=True) generates __eq__
        # based on all compare=True fields, and sort_index is (timestamp_nanos, job_id).
        # Two jobs with the same sort_index necessarily share the same job_id (job_id
        # comes from itertools.count in __post_init__), so the hash contract
        # (a == b implies hash(a) == hash(b)) holds. If sort_index ever stops
        # including job_id, this __hash__ MUST be re-evaluated.
        return hash(self.job_id)

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, owner_id={self.owner_id})"

    def __post_init__(self):
        self.set_next_run(self.next_run)

        if not self.name:
            callable_name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)
            # All triggers implement TriggerProtocol and expose trigger_id() for unique naming.
            trigger_str = self.trigger.trigger_id() if self.trigger is not None else None
            self.name = f"{callable_name}:{trigger_str}" if self.trigger else callable_name

        self.args = tuple(self.args)
        self.kwargs = dict(self.kwargs)

    def mark_registered(self, db_id: int) -> None:
        """Set the database ID after persistence. One-time assignment by SchedulerService."""
        if self.db_id is not None:
            LOGGER.warning(
                "ScheduledJob %s already registered with db_id=%s, ignoring new db_id=%s",
                self.job_id,
                self.db_id,
                db_id,
            )
            return
        self.db_id = db_id

    def matches(self, other: "ScheduledJob") -> bool:
        """Check whether two jobs represent the same logical configuration.

        Compares callable, trigger (by trigger_id()), group, args, and kwargs.
        Does not compare runtime state (job_id, next_run, sort_index, cancelled, owner).

        Two jobs with identical callable/trigger/args but different groups are distinct
        logical jobs and will not match.
        """
        if self.trigger is not None and other.trigger is not None:
            triggers_match = self.trigger.trigger_id() == other.trigger.trigger_id()
        else:
            triggers_match = self.trigger is other.trigger
        return (
            self.job == other.job
            and triggers_match
            and self.group == other.group
            and self.args == other.args
            and self.kwargs == other.kwargs
        )

    def cancel(self) -> None:
        """Cancel the scheduled job by setting the cancelled flag to True."""
        self.cancelled = True

    def set_next_run(self, next_run: ZonedDateTime) -> None:
        """Update the next run timestamp, fire_at, and ordering metadata.

        Both ``next_run`` and ``fire_at`` are set to the rounded value. Call
        ``SchedulerService._apply_jitter_to_heap()`` after this to set a jittered
        ``fire_at`` when the job has ``jitter`` configured.
        """
        rounded = next_run.round(unit="second")
        self.next_run = rounded
        self.fire_at = rounded
        self.sort_index = (rounded.timestamp_nanos(), self.job_id)


@dataclass(frozen=True)
class JobExecutionRecord:
    """Record of a single job execution for metrics tracking."""

    job_id: int | None
    """FK to the scheduled_jobs table entry for this job. None for framework-internal jobs."""

    session_id: int | None
    """Session during which the execution occurred.

    None when enqueued before session creation; injected at drain time.
    """

    execution_start_ts: float
    """Unix timestamp (epoch seconds) when execution began."""

    duration_ms: float
    status: str  # "success", "error", "cancelled"
    source_tier: SourceTier = "app"
    """Whether this execution originates from a user app or the framework itself."""

    is_di_failure: bool = False
    """True when the execution failed due to a DependencyError (or subclass)."""

    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
