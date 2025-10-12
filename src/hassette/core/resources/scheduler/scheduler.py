import asyncio
import typing
from collections.abc import Mapping
from typing import Any

from whenever import SystemDateTime, TimeDelta

from hassette.core.resources.base import Resource
from hassette.core.resources.scheduler.classes import CronTrigger, IntervalTrigger, ScheduledJob
from hassette.core.services.scheduler_service import _SchedulerService
from hassette.utils.date_utils import now

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.types import JobCallable, TriggerProtocol


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
        run_at: SystemDateTime,
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a specific time.

        Args:
            func (JobCallable): The function to run.
            run_at (SystemDateTime): The time to run the job.
            name (str): Optional name for the job.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        return self.schedule(func, run_at, name=name, args=args, kwargs=kwargs)

    def run_at(
        self,
        func: "JobCallable",
        run_at: SystemDateTime,
        name: str = "",
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Alias for `run_once`, schedule a job to run at a specific time.

        Args:
            func (JobCallable): The function to run.
            run_at (SystemDateTime): The time to run the job.
            name (str): Optional name for the job.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.
        Returns:
            ScheduledJob: The scheduled job.
        """

        return self.run_once(func, run_at, name=name, args=args, kwargs=kwargs)

    def run_every(
        self,
        func: "JobCallable",
        interval: TimeDelta | float,
        name: str = "",
        start: SystemDateTime | None = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a fixed interval.

        Args:
            func (JobCallable): The function to run.
            interval (TimeDelta | float): The interval between runs.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the interval.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        interval_seconds = interval if isinstance(interval, float | int) else interval.in_seconds()

        first_run = start if start else now().add(seconds=interval_seconds)
        trigger = IntervalTrigger.from_arguments(seconds=interval_seconds, start=first_run)

        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_in(
        self,
        func: "JobCallable",
        delay: TimeDelta | float,
        name: str = "",
        start: SystemDateTime | None = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run after a delay.

        Args:
            func (JobCallable): The function to run.
            delay (TimeDelta | float): The delay before running the job.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the delay.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """

        delay_seconds = delay if isinstance(delay, float | int) else delay.in_seconds()

        run_at = start if start else now().add(seconds=delay_seconds)
        return self.schedule(func, run_at, name=name, args=args, kwargs=kwargs)

    def run_minutely(
        self,
        func: "JobCallable",
        minute: int = 1,
        name: str = "",
        start: SystemDateTime | None = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N minutes.

        Args:
            func (JobCallable): The function to run.
            minute (int): The minute interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the top of the next minute interval.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if minute < 1:
            raise ValueError("Minute interval must be at least 1")

        trigger = IntervalTrigger.from_arguments(minutes=minute, start=start)
        first_run = start if start else now().replace(second=0, nanosecond=0)
        if first_run <= now():
            first_run = first_run.add(minutes=minute)

        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_hourly(
        self,
        func: "JobCallable",
        hour: int = 1,
        name: str = "",
        start: SystemDateTime | None = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N hours.

        Args:
            func (JobCallable): The function to run.
            hour (int): The hour interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise, the job will run immediately at the next hour boundary, then repeat every N hours.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if hour < 1:
            raise ValueError("Hour interval must be at least 1")

        trigger = IntervalTrigger.from_arguments(hours=hour, start=start)
        first_run = start if start else now().replace(minute=0, second=0, nanosecond=0)
        if first_run <= now():
            first_run = first_run.add(hours=hour)

        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)

    def run_daily(
        self,
        func: "JobCallable",
        day: int = 1,
        name: str = "",
        start: SystemDateTime | None = None,
        *,
        args: tuple[Any, ...] | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run every N days.

        Args:
            func (JobCallable): The function to run.
            day (int): The day interval to run the job.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at midnight plus the day interval.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        if day < 1:
            raise ValueError("Day interval must be at least 1")

        hours = 24 * day

        trigger = IntervalTrigger.from_arguments(hours=hours, start=start)
        first_run = start if start else now().replace(hour=0, minute=0, second=0, nanosecond=0)
        if first_run <= now():
            first_run = first_run.add(hours=hours)

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
        start: SystemDateTime | None = None,
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
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the cron schedule.
            args (tuple[Any, ...] | None): Positional arguments to pass to the callable when it executes.
            kwargs (Mapping[str, Any] | None): Keyword arguments to pass to the callable when it executes.

        Returns:
            ScheduledJob: The scheduled job.
        """
        trigger = CronTrigger.from_arguments(
            second=second,
            minute=minute,
            hour=hour,
            day_of_month=day_of_month,
            month=month,
            day_of_week=day_of_week,
            start=start,
        )
        run_at = trigger.next_run_time()
        return self.schedule(func, run_at, trigger=trigger, repeat=True, name=name, args=args, kwargs=kwargs)
