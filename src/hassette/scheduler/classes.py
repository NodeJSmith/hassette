import itertools
import logging
import typing
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self, TypeVar

from croniter import croniter
from whenever import TimeDelta, ZonedDateTime

from hassette.utils.date_utils import now

if typing.TYPE_CHECKING:
    from hassette.types import JobCallable, TriggerProtocol


LOGGER = logging.getLogger(__name__)

seq = itertools.count(1)

T = TypeVar("T")


def next_id() -> int:
    return next(seq)


class IntervalTrigger:
    """A trigger that runs at a fixed interval."""

    def __init__(self, interval: TimeDelta, start: ZonedDateTime | None = None):
        self.interval = interval
        self.start = start or now()

    @classmethod
    def from_arguments(
        cls,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        start: ZonedDateTime | None = None,
    ) -> Self:
        return cls(TimeDelta(hours=hours, minutes=minutes, seconds=seconds), start=start)

    def next_run_time(self) -> ZonedDateTime:
        # Catch up if we're behind schedule
        while (next_time := self.start.add(seconds=self.interval.in_seconds())) <= now():
            LOGGER.debug("Skipping past interval time %s", next_time)
            self.start = self.start.add(seconds=self.interval.in_seconds())

        # Advance to the next scheduled time
        self.start = self.start.add(seconds=self.interval.in_seconds())

        return self.start.round(unit="second")


class CronTrigger:
    """A trigger that runs based on a cron expression."""

    def __init__(self, cron_expression: str, start: ZonedDateTime | None = None):
        self.cron_expression = cron_expression
        base = start or now()
        self.cron_iter = croniter(cron_expression, base.py_datetime(), ret_type=datetime)

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

    def next_run_time(self) -> ZonedDateTime:
        while (next_time := self.cron_iter.get_next()) <= now().py_datetime():
            delta = now() - ZonedDateTime.from_py_datetime(next_time)
            if delta.in_seconds() > 60:
                LOGGER.warning(
                    "Cron schedule is more than 1 minute (%s) behind the current time; "
                    "Next scheduled time: %s, now: %s",
                    delta.in_minutes(),
                    next_time,
                    now().py_datetime(),
                )
                self.cron_iter.set_current(now().py_datetime())

            LOGGER.debug("Skipping past cron time %s", next_time)
            pass

        return ZonedDateTime.from_py_datetime(next_time)


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    sort_index: tuple[int, int] = field(init=False, repr=False)
    """Tuple of (next_run timestamp with nanoseconds, job_id) for ordering in a priority queue."""

    owner: str = field(compare=False)
    """Unique string identifier for the owner of the job, e.g., a component or integration name."""

    next_run: ZonedDateTime = field(compare=False)
    """Timestamp of the next scheduled run."""

    job: "JobCallable" = field(compare=False)
    """The callable to execute when the job runs."""

    trigger: "TriggerProtocol | None" = field(compare=False, default=None)
    """The trigger that determines the job's schedule."""

    repeat: bool = field(compare=False, default=False)
    """Whether the job should be rescheduled after running."""

    timeout_seconds: int = field(compare=False, default=30)
    """Maximum allowed execution time for the job in seconds."""

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

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, owner={self.owner})"

    def __post_init__(self):
        self.set_next_run(self.next_run)

        if not self.name:
            self.name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)

        self.args = tuple(self.args)
        self.kwargs = dict(self.kwargs)

    def cancel(self) -> None:
        """Cancel the scheduled job by setting the cancelled flag to True."""
        self.cancelled = True

    def set_next_run(self, next_run: ZonedDateTime) -> None:
        """Update the next run timestamp and refresh ordering metadata."""
        rounded_next_run = next_run.round(unit="second")
        self.next_run = rounded_next_run
        self.sort_index = (next_run.timestamp_nanos(), self.job_id)
