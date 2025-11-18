"""
Scheduler for running tasks at specific times or intervals with flexible triggers.

The Scheduler provides intuitive methods for scheduling one-time and recurring tasks using
cron expressions, intervals, or simple time delays. Jobs are automatically cleaned up when
the app shuts down, and support both async and sync callables.

Examples:
    One-time delayed execution

    ```python
    # Run in 30 seconds
    self.scheduler.run_in(self.cleanup_task, 30)

    # Run at specific datetime
    self.scheduler.run_once(self.morning_routine, "2023-12-25 09:00:00")
    ```

    Recurring execution with intervals

    ```python
    # Every 5 minutes
    self.scheduler.run_every(self.check_sensors, interval=300)

    # Every hour starting in 10 minutes
    self.scheduler.run_every(
        self.hourly_report,
        interval=3600,
        start_in=600
    )
    ```

    Time-based recurring schedules

    ```python
    # Every hour at 15 minutes past
    self.scheduler.run_hourly(self.log_status, minute=15)

    # Daily at 6:30 AM
    self.scheduler.run_daily(self.morning_routine, hour=6, minute=30)

    # Every minute at 30 seconds
    self.scheduler.run_minutely(self.quick_check, second=30)
    ```

    Cron-style scheduling

    ```python
    # Weekdays at 9 AM
    self.scheduler.run_cron(
        self.workday_routine,
        hour=9,
        minute=0,
        day_of_week="mon-fri"
    )

    # Every 15 minutes during business hours
    self.scheduler.run_cron(
        self.business_check,
        minute="*/15",
        hour="9-17",
        day_of_week="mon-fri"
    )
    ```

    Using trigger objects for complex scheduling

    ```python
    from hassette.scheduler import CronTrigger, IntervalTrigger

    # Complex cron trigger
    trigger = CronTrigger(
        hour="*/2",
        minute=30,
        day_of_week="mon,wed,fri"
    )
    self.scheduler.schedule(self.complex_task, trigger=trigger)

    # Interval with custom start time
    trigger = IntervalTrigger(
        interval=timedelta(minutes=30),
        start_datetime=datetime(2023, 12, 1, 8, 0)
    )
    self.scheduler.schedule(self.periodic_task, trigger=trigger)
    ```

    Job management and naming

    ```python
    # Named job for easier management
    job = self.scheduler.run_daily(
        self.backup_data,
        hour=2,
        minute=0,
        name="daily_backup"
    )

    # Remove specific job
    self.scheduler.remove_job(job)

    # Remove all jobs for this scheduler
    self.scheduler.remove_all_jobs()
    ```
"""

import asyncio
import typing
from collections.abc import Mapping
from datetime import time
from typing import Any

from whenever import Time, TimeDelta, ZonedDateTime

from hassette.core.scheduler_service import SchedulerService
from hassette.resources.base import Resource
from hassette.utils.date_utils import now

from .classes import CronTrigger, IntervalTrigger, ScheduledJob

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import JobCallable, ScheduleStartType, TriggerProtocol


class Scheduler(Resource):
    """Scheduler resource for managing scheduled jobs."""

    scheduler_service: SchedulerService
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
            job: The job to add.

        Returns:
            The added job.
        """

        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")

        self.scheduler_service.add_job(job)

        return job

    def remove_job(self, job: "ScheduledJob") -> asyncio.Task:
        """Remove a job from the scheduler.

        Args:
            job: The job to remove.
        """

        return self.scheduler_service.remove_job(job)

    def remove_all_jobs(self) -> asyncio.Task:
        """Remove all jobs for the owner of this scheduler."""
        return self.scheduler_service.remove_jobs_by_owner(self.owner_id)

    def schedule(
        self,
        func: "JobCallable",
        run_at: ZonedDateTime,
        trigger: "TriggerProtocol | None" = None,
        repeat: bool = False,
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a specific time or based on a trigger.

        Args:
            func: The function to run.
            run_at: The time to run the job.
            trigger: Optional trigger for repeating jobs.
            repeat: Whether the job should repeat.
            name: Optional name for the job.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
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
        start: "ScheduleStartType",
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run once at a specific time.

        Args:
            func: The function to run.
            start: The time to run the job.
            name: Optional name for the job.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
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
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a fixed interval.

        Args:
            func: The function to run.
            interval: The interval between runs. If a float is provided, it is treated as seconds.
            name: Optional name for the job.
            start: Optional start time for the first run. If provided the job will run at this time. Otherwise it will
                run at the current time plus the interval.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
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
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run after a delay.

        Args:
            func: The function to run.
            delay: The delay before running the job.
            name: Optional name for the job.
            start: Optional start time for the job. If provided the job will run at this time, otherwise it will run at
                the current time plus the delay.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
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
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N minutes.

        Args:
            func: The function to run.
            minutes: The minute interval to run the job.
            name: Optional name for the job.
            start: Optional start time for the first run. If provided the job will run at this time. Otherwise, the job
                will run at now + N minutes.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        if minutes < 1:
            raise ValueError("Minute interval must be at least 1")

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(minutes=minutes, start=start_dtme)
        first_run = start_dtme if start_dtme else now().add(minutes=minutes)
        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_hourly(
        self,
        func: "JobCallable",
        hours: int = 1,
        name: str = "",
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N hours.

        Args:
            func: The function to run.
            hours: The hour interval to run the job.
            name: Optional name for the job.
            start: Optional start time for the first run. If provided the job will run at this time, otherwise the job
                will run at now + N hours.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        if hours < 1:
            raise ValueError("Hour interval must be at least 1")

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(hours=hours, start=start_dtme)
        first_run = start_dtme if start_dtme else now().add(hours=hours)
        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_daily(
        self,
        func: "JobCallable",
        days: int = 1,
        name: str = "",
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N days.

        Args:
            func: The function to run.
            days: The day interval to run the job.
            name: Optional name for the job.
            start: Optional start time for the first run. If provided the job will run at this time, otherwise the job
                will run at now + N days.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
        """
        if days < 1:
            raise ValueError("Day interval must be at least 1")
        if days > 365:
            raise ValueError("Day interval must not exceed 365")

        hours = 24 * days

        start_dtme = get_start_dtme(start)

        trigger = IntervalTrigger.from_arguments(hours=hours, start=start_dtme)
        first_run = start_dtme if start_dtme else now().add(hours=hours)
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
        start: "ScheduleStartType" = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job using a cron expression.

        Uses a 6-field format (seconds, minutes, hours, day of month, month, day of week).

        Args:
            func: The function to run.
            second: Seconds field of the cron expression.
            minute: Minutes field of the cron expression.
            hour: Hours field of the cron expression.
            day_of_month: Day of month field of the cron expression.
            month: Month field of the cron expression.
            day_of_week: Day of week field of the cron expression.
            name: Optional name for the job.
            start: Optional start time for the first run. If provided the job will run at this time, otherwise the job
                will run at the next scheduled time based on the cron expression.
            args: Positional arguments to pass to the callable when it executes.
            kwargs: Keyword arguments to pass to the callable when it executes.

        Returns:
            The scheduled job.
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


def get_start_dtme(start: "ScheduleStartType") -> ZonedDateTime | None:
    """Convert a start time to a ZonedDateTime.

    Args:
        start: The start time to convert.

    Returns:
        The converted start time, or None if no start time was provided.

    Raises:
        TypeError: If the start time is not a valid type.
    """
    start_dtme: ZonedDateTime | None = None

    if start is None:
        return start

    if isinstance(start, ZonedDateTime):
        # provided as a full datetime, just use it
        return start

    if isinstance(start, TimeDelta):
        # we can add these directly to get a new ZonedDateTime
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

    # convert to ZonedDateTime for today at the specified time
    # if this ends up in the past, the trigger will handle advancing to the next valid time
    start_dtme = ZonedDateTime.from_system_tz(
        year=now().year, month=now().month, day=now().day, hour=start_time.hour, minute=start_time.minute
    )
    return start_dtme
