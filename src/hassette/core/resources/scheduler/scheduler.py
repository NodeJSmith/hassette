import asyncio
import typing
from collections.abc import Mapping
from datetime import time
from typing import Any

from whenever import SystemDateTime, Time, TimeDelta

from hassette.core.resources.base import Resource
from hassette.core.resources.scheduler.classes import CronTrigger, IntervalTrigger, ScheduledJob
from hassette.core.services.scheduler_service import _SchedulerService
from hassette.utils.date_utils import now

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import JobCallable, TriggerProtocol

HOUR_MIN = tuple[int, int]
"""A tuple representing an hour and minute."""

START_TYPE = SystemDateTime | Time | time | HOUR_MIN | TimeDelta | int | float | None
"""Type for specifying start times."""


class Scheduler(Resource):
    """Scheduler resource for managing scheduled jobs."""

    scheduler_service: _SchedulerService
    """The scheduler service instance."""

    @classmethod
    def create(cls, hassette: "Hassette", parent: "Resource"):
        inst = cls(hassette=hassette, parent=parent)
        inst.scheduler_service = inst.hassette._scheduler_service
        assert inst.scheduler_service is not None, "Scheduler service not initialized"

        inst.mark_ready(reason="Scheduler initialized")
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.scheduler_service_log_level

    def add_job(self, job: "ScheduledJob") -> "ScheduledJob":
        """Add a job to the scheduler.

        Args:
            job (ScheduledJob): The job to add.

        Returns:
            ScheduledJob: The added job.
        """

        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")

        self.scheduler_service.add_job(job)

        return job

    def remove_job(self, job: "ScheduledJob") -> asyncio.Task:
        """Remove a job from the scheduler.

        Args:
            job (ScheduledJob): The job to remove.
        """

        return self.scheduler_service.remove_job(job)

    def remove_all_jobs(self) -> asyncio.Task:
        """Remove all jobs for the owner of this scheduler."""
        return self.scheduler_service.remove_jobs_by_owner(self.owner_id)

    def schedule(
        self,
        func: "JobCallable",
        run_at: SystemDateTime,
        trigger: "TriggerProtocol | None" = None,
        repeat: bool = False,
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a specific time or based on a trigger.

        Args:
            func (JobCallable): The function to run.
            run_at (SystemDateTime): The time to run the job.
            trigger (TriggerProtocol | None): Optional trigger for repeating jobs.
            repeat (bool): Whether the job should repeat.
            name (str): Optional name for the job.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        job = ScheduledJob(
            owner=self.owner_id,
            next_run=run_at,
            job=func,
            trigger=trigger,
            repeat=repeat,
            name=name,
            args=tuple(args) if args else (),
            kwargs=dict(kwargs) if kwargs else {},
        )
        return self.add_job(job)

    def run_once(
        self,
        func: "JobCallable",
        start: START_TYPE,
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run once at a specific time.

        Args:
            func (JobCallable): The function to run.
            start (START_TYPE): The time to run the job. Can be a SystemDateTime, Time, time, or (hour, minute) tuple.
            name (str): Optional name for the job.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.
        Returns:
            ScheduledJob: The scheduled job.
        """

        start_dtme = get_start_dtme(start)
        if start_dtme is None:
            raise ValueError("start must be a valid start time")

        return self.schedule(func, start_dtme, name=name, args=args, kwargs=kwargs)

    def run_every(
        self,
        func: "JobCallable",
        interval: TimeDelta | float,
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a fixed interval.

        Args:
            func (JobCallable): The function to run.
            interval (TimeDelta | float): The interval between runs. If a float is provided, it is treated as seconds.
            name (str): Optional name for the job.
            start (START_TYPE): Optional start time for the first run. If provided the job will run at this time plus\
                 the interval. Otherwise it will run at the current time plus the interval.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        interval_seconds = interval if isinstance(interval, float | int) else interval.in_seconds()

        start_dtme = get_start_dtme(start)

        first_run = start_dtme if start_dtme else now().add(seconds=interval_seconds)
        trigger = IntervalTrigger.from_arguments(seconds=interval_seconds, start=first_run)

        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_in(
        self,
        func: "JobCallable",
        delay: TimeDelta | float,
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run after a delay.

        Args:
            func (JobCallable): The function to run.
            delay (TimeDelta | float): The delay before running the job.
            name (str): Optional name for the job.
            start (START_TYPE): Optional start time for the job. If provided the job will run at this time plus the\
                delay. Otherwise it will run at the current time plus the delay.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        delay_seconds = delay if isinstance(delay, float | int) else delay.in_seconds()

        start_dtme = get_start_dtme(start)

        run_at = start_dtme if start_dtme else now().add(seconds=delay_seconds)
        return self.schedule(func, run_at, name=name, args=args, kwargs=kwargs)

    def run_minutely(
        self,
        func: "JobCallable",
        minutes: int = 1,
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N minutes.

        Args:
            func (JobCallable): The function to run.
            minutes (int): The minute interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | Time | time | HOUR_MIN | None): Optional start time for the first run. If\
                provided the job will run at this time. Otherwise, the job will run immediately, then repeat every\
                N minutes.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if minutes < 1:
            raise ValueError("Minute interval must be at least 1")

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(minutes=minutes, start=start_dtme)
        first_run = start_dtme if start_dtme else now()
        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_hourly(
        self,
        func: "JobCallable",
        hours: int = 1,
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N hours.

        Args:
            func (JobCallable): The function to run.
            hours (int): The hour interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | Time | time | HOUR_MIN | None): Optional start time for the first run. If\
                provided the job will run at this time. Otherwise, the job will run immediately, then repeat every\
                N hours.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if hours < 1:
            raise ValueError("Hour interval must be at least 1")

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(hours=hours, start=start_dtme)
        first_run = start_dtme if start_dtme else now()
        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_daily(
        self,
        func: "JobCallable",
        days: int = 1,
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N days.

        Args:
            func (JobCallable): The function to run.
            days (int): The day interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | Time | time | HOUR_MIN | None): Optional start time for the first run. If\
                provided the job will run at this time. Otherwise, the job will run immediately, then repeat every\
                N days.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if days < 1:
            raise ValueError("Day interval must be at least 1")
        if days > 365:
            raise ValueError("Day interval must not exceed 365")

        hours = 24 * days

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(hours=hours, start=start_dtme)
        first_run = start_dtme if start_dtme else now()
        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_cron(
        self,
        func: "JobCallable",
        second: int | str = 0,
        minute: int | str = 0,
        hour: int | str = 0,
        day_of_month: int | str = "*",
        month: int | str = "*",
        day_of_week: int | str = "*",
        name: str = "",
        start: START_TYPE = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job using a cron expression.

        Uses a 6-field format (seconds, minutes, hours, day of month, month, day of week).

        Args:
            func (JobCallable): The function to run.
            second (int | str): Seconds field of the cron expression.
            minute (int | str): Minutes field of the cron expression.
            hour (int | str): Hours field of the cron expression.
            day_of_month (int | str): Day of month field of the cron expression.
            month (int | str): Month field of the cron expression.
            day_of_week (int | str): Day of week field of the cron expression.
            name (str): Optional name for the job.
            start (START_TYPE): Optional start time for the first run. If provided the job will run at this time.\
                Otherwise, the job will run at the next scheduled time based on the cron expression.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        start_dtme = get_start_dtme(start)

        trigger = CronTrigger.from_arguments(
            second=second,
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month=month,
            day_of_week=day_of_week,
            start=start_dtme,
        )
        run_at = trigger.next_run_time()
        return self.schedule(func, run_at, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)


def get_start_dtme(start: START_TYPE) -> SystemDateTime | None:
    """Convert a start time to a SystemDateTime.

    Args:
        start (START_TYPE): The start time to convert. Can be a SystemDateTime, Time, time, or (hour, minute) tuple.

    Returns:
        SystemDateTime | None: The converted start time, or None if no start time was provided.

    Raises:
        TypeError: If the start time is not a valid type.
    """
    start_dtme: SystemDateTime | None = None

    if start is None:
        return start

    if isinstance(start, SystemDateTime):
        # provided as a full datetime, just use it
        return start

    if isinstance(start, TimeDelta):
        # we can add these directly to get a new SystemDateTime
        return now() + start

    # if we have time/Time then no change
    # if we have (hour, minute) tuple then convert to time
    if isinstance(start, Time | time):
        start_time = start
    elif isinstance(start, tuple) and len(start) == 2:
        if not all(isinstance(x, int) for x in start):
            raise TypeError(f"Start time tuple must contain two integers (hour, minute), got {start}")
        start_time = time(*start)
    elif isinstance(start, int | float):
        # treat as seconds from now
        return now().add(seconds=start)
    else:
        raise TypeError(f"Start time must be a Time, time, or (hour, minute) tuple, got {type(start).__name__}")

    # convert to SystemDateTime for today at the specified time
    # if this ends up in the past, the trigger will handle advancing to the next valid time
    start_dtme = SystemDateTime(
        year=now().year, month=now().month, day=now().day, hour=start_time.hour, minute=start_time.minute
    )
    return start_dtme
