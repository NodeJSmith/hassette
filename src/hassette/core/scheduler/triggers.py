import logging
from datetime import datetime
from typing import Self

from croniter import croniter
from whenever import SystemDateTime, TimeDelta

LOGGER = logging.getLogger(__name__)


def now() -> SystemDateTime:
    """Get the current time.

    This exists to avoid direct calls to SystemDateTime.now() in the codebase, in case we need to change
    the implementation later.
    """
    return SystemDateTime.now()


class IntervalTrigger:
    """A trigger that runs at a fixed interval."""

    def __init__(self, interval: TimeDelta, start: SystemDateTime | None = None):
        self.interval = interval
        self.start = start or now()

    @classmethod
    def from_arguments(
        cls,
        hours: float = 0,
        minutes: float = 0,
        seconds: float = 0,
        start: SystemDateTime | None = None,
    ) -> Self:
        return cls(TimeDelta(hours=hours, minutes=minutes, seconds=seconds), start=start)

    def next_run_time(self) -> SystemDateTime:
        # Catch up if we're behind schedule
        while (next_time := self.start.add(seconds=self.interval.in_seconds())) <= now():
            LOGGER.debug("Skipping past interval time %s", next_time)
            self.start = self.start.add(seconds=self.interval.in_seconds())

        # Advance to the next scheduled time
        self.start = self.start.add(seconds=self.interval.in_seconds())

        return self.start.round(unit="second")


class CronTrigger:
    """A trigger that runs based on a cron expression."""

    def __init__(self, cron_expression: str, start: SystemDateTime | None = None):
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
        start: SystemDateTime | None = None,
    ) -> Self:
        """Create a CronTrigger from individual cron fields.

        Uses a 6-field format (seconds, minutes, hours, day of month, month, day of week).

        Args:
            second (int | str): Seconds field of the cron expression.
            minute (int | str): Minutes field of the cron expression.
            hour (int | str): Hours field of the cron expression.
            day_of_month (int | str): Day of month field of the cron expression.
            month (int | str): Month field of the cron expression.
            day_of_week (int | str): Day of week field of the cron expression.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the cron schedule.

        Returns:
            CronTrigger: The cron trigger.
        """

        # seconds is not supported by Unix cron, but croniter supports it
        # however, croniter expects it to be after DOW field, so that's what we do here
        cron_expression = f"{minute} {hour} {day_of_month} {month} {day_of_week} {second}"

        if not croniter.is_valid(cron_expression):
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        return cls(cron_expression, start=start)

    def next_run_time(self) -> SystemDateTime:
        while (next_time := self.cron_iter.get_next()) <= now().py_datetime():
            delta = now() - SystemDateTime.from_py_datetime(next_time)
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

        return SystemDateTime.from_py_datetime(next_time)
