import itertools
import typing
from dataclasses import dataclass, field
from datetime import datetime
from logging import getLogger
from typing import Any, Self

from croniter import croniter
from whenever import TimeDelta, ZonedDateTime

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


class IntervalTrigger:
    """A trigger that runs at a fixed interval."""

    def __init__(self, interval: TimeDelta, start: ZonedDateTime | None = None):
        if interval.in_seconds() <= 0:
            raise ValueError("IntervalTrigger interval must be positive")
        self.interval = interval
        self.start = start or date_utils.now()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IntervalTrigger):
            return NotImplemented
        return self.interval == other.interval

    def __hash__(self) -> int:
        return hash(self.interval)

    def __str__(self) -> str:
        return f"interval:{self.interval.in_seconds():g}s"

    def trigger_id(self) -> str:
        """Bridge method for TriggerProtocol compatibility. WP03 will remove IntervalTrigger.

        The ``"every:"`` prefix is intentionally shared with ``Every.trigger_id()`` so that
        an ``IntervalTrigger(hours=1)`` job and an ``Every(hours=1)`` job are treated as the
        same logical job by ``ScheduledJob.matches()`` during the migration window.
        """
        return f"every:{int(self.interval.in_seconds())}"

    @classmethod
    def from_arguments(
        cls,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        start: ZonedDateTime | None = None,
    ) -> Self:
        """Create an IntervalTrigger from separate hours/minutes/seconds components."""
        return cls(TimeDelta(hours=hours, minutes=minutes, seconds=seconds), start=start)

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the first scheduled run time at or after current_time."""
        if self.start > current_time:
            return self.start.round(unit="second")
        return self._advance_past(self.start, current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        """Return the next run time after previous_run that is later than current_time."""
        return self._advance_past(previous_run, current_time)

    def _advance_past(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        interval_secs = self.interval.in_seconds()
        elapsed = (current_time - anchor).in_seconds()
        if elapsed > 0:
            missed = int(elapsed / interval_secs)
            anchor = anchor.add(seconds=missed * interval_secs)
        result = anchor.add(seconds=interval_secs)
        # Guard: if floating-point truncation landed result at or before current_time,
        # advance one more interval. Boundary-exact slots are treated as "past."
        if result <= current_time:
            result = result.add(seconds=interval_secs)
        return result.round(unit="second")


class CronTrigger:
    """A trigger that runs based on a cron expression."""

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

    def trigger_id(self) -> str:
        """Bridge method for TriggerProtocol compatibility. WP03 will remove CronTrigger."""
        return f"cron:{self.cron_expression}"

    @classmethod
    def from_arguments(
        cls,
        second: int | str = 0,
        minute: int | str = 0,
        hour: int | str = 0,
        day_of_month: int | str = "*",
        month: int | str = "*",
        day_of_week: int | str = "*",
        start: ZonedDateTime | None = None,
    ) -> Self:
        """Create a CronTrigger from individual cron fields.

        Uses a 6-field format (seconds, minutes, hours, day of month, month, day of week).

        Args:
            second: Seconds field of the cron expression.
            minute: Minutes field of the cron expression.
            hour: Hours field of the cron expression.
            day_of_month: Day of month field of the cron expression.
            month: Month field of the cron expression.
            day_of_week: Day of week field of the cron expression.
            start: Optional start time for the first run. If provided the job will run at this time.
                Otherwise it will run at the current time plus the cron schedule.

        Returns:
            The cron trigger.
        """

        # seconds is not supported by Unix cron, but croniter supports it
        # however, croniter expects it to be after DOW field, so that's what we do here
        cron_expression = f"{minute} {hour} {day_of_month} {month} {day_of_week} {second}"

        if not croniter.is_valid(cron_expression):
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        return cls(cron_expression, start=start)

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
        current_dt = current_time.py_datetime()
        # Bounded iteration — avoids O(N) spin for sub-second crons after long downtime.
        # 10,000 iterations covers ~2.7 hours of per-second crons, which is generous.
        max_iterations = 10_000
        for _ in range(max_iterations):
            next_time = cron.get_next()
            if next_time > current_dt:
                return ZonedDateTime.from_py_datetime(next_time)
        # Too many iterations — skip ahead from current time
        LOGGER.warning(
            "CronTrigger(%s) exceeded %d iterations catching up, skipping ahead from current_time",
            self.cron_expression,
            max_iterations,
        )
        cron = croniter(self.cron_expression, current_dt, ret_type=datetime)
        next_time = cron.get_next()
        return ZonedDateTime.from_py_datetime(next_time)


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    sort_index: tuple[int, int] = field(init=False, repr=False)
    """Tuple of (next_run timestamp with nanoseconds, job_id) for ordering in a priority queue."""

    owner_id: str = field(compare=False)
    """Unique string identifier for the owner of the job, e.g., a component or integration name."""

    next_run: ZonedDateTime = field(compare=False)
    """Unjittered logical fire time — used as `previous_run` in subsequent trigger calls."""

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
    """Seconds of random offset applied at enqueue time. Does not affect next_run (unjittered).

    TODO(WP06): apply ``random.uniform(0, jitter)`` to the sort_index offset at enqueue time.
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

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, owner_id={self.owner_id})"

    def __post_init__(self):
        self.set_next_run(self.next_run)

        if not self.name:
            callable_name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)
            # TriggerProtocol types expose trigger_label(); legacy IntervalTrigger/CronTrigger use __str__.
            trigger_str = self.trigger.trigger_label() if hasattr(self.trigger, "trigger_label") else str(self.trigger)
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
        """Update the next run timestamp and refresh ordering metadata."""
        rounded = next_run.round(unit="second")
        self.next_run = rounded
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
