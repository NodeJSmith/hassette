import itertools
import logging
import typing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from croniter import croniter
from whenever import TimeDelta, ZonedDateTime

from hassette.utils.date_utils import now

if typing.TYPE_CHECKING:
    from hassette.types import JobCallable, TriggerProtocol


LOGGER = logging.getLogger(__name__)

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
        self.start = start or now()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IntervalTrigger):
            return NotImplemented
        return self.interval == other.interval

    def __hash__(self) -> int:
        return hash(self.interval)

    def __str__(self) -> str:
        return f"interval:{self.interval.in_seconds():g}s"

    @classmethod
    def from_arguments(
        cls,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        start: ZonedDateTime | None = None,
    ) -> Self:
        return cls(TimeDelta(hours=hours, minutes=minutes, seconds=seconds), start=start)

    def first_run_time(self, current_time: ZonedDateTime) -> ZonedDateTime:
        if self.start > current_time:
            return self.start.round(unit="second")
        return self._advance_past(self.start, current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
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
        base = start or now()
        croniter(cron_expression, base.py_datetime(), ret_type=datetime)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CronTrigger):
            return NotImplemented
        return self.cron_expression == other.cron_expression

    def __hash__(self) -> int:
        return hash(self.cron_expression)

    def __str__(self) -> str:
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
        return self._next_after(self.start or current_time, current_time)

    def next_run_time(self, previous_run: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        return self._next_after(previous_run, current_time)

    def _next_after(self, anchor: ZonedDateTime, current_time: ZonedDateTime) -> ZonedDateTime:
        # No fixed skip-ahead threshold — croniter efficiently handles coarse schedules
        # (a daily cron iterates once regardless of gap). Only sub-second crons with
        # multi-minute gaps iterate heavily, which is rare in home automation.
        cron = croniter(self.cron_expression, anchor.py_datetime(), ret_type=datetime)
        while (next_time := cron.get_next()) <= current_time.py_datetime():
            pass
        return ZonedDateTime.from_py_datetime(next_time)


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    sort_index: tuple[int, int] = field(init=False, repr=False)
    """Tuple of (next_run timestamp with nanoseconds, job_id) for ordering in a priority queue."""

    owner_id: str = field(compare=False)
    """Unique string identifier for the owner of the job, e.g., a component or integration name."""

    next_run: ZonedDateTime = field(compare=False)
    """Timestamp of the next scheduled run."""

    job: "JobCallable" = field(compare=False)
    """The callable to execute when the job runs."""

    app_key: str = field(default="", compare=False)
    """Configuration-level app key for DB registration (e.g., 'my_app'). Empty for non-App owners."""

    instance_index: int = field(default=0, compare=False)
    """App instance index for DB registration. 0 for non-App owners."""

    trigger: "TriggerProtocol | None" = field(compare=False, default=None)
    """The trigger that determines the job's schedule."""

    repeat: bool = field(compare=False, default=False)
    """Whether the job should be rescheduled after running."""

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

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, owner_id={self.owner_id})"

    def __post_init__(self):
        self.set_next_run(self.next_run)

        if not self.name:
            callable_name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)
            self.name = f"{callable_name}:{self.trigger}" if self.trigger else callable_name

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

        Compares the callable, trigger, repeat flag, args, and kwargs. Does not compare
        runtime state (job_id, next_run, sort_index, cancelled, owner).
        """
        return (
            self.job == other.job
            and self.trigger == other.trigger
            and self.repeat == other.repeat
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

    job_id: int
    """FK to the scheduled_jobs table entry for this job."""

    session_id: int
    """Session during which the execution occurred."""

    execution_start_ts: float
    """Unix timestamp (epoch seconds) when execution began."""

    duration_ms: float
    status: str  # "success", "error", "cancelled"
    error_message: str | None = None
    error_type: str | None = None
    error_traceback: str | None = None
