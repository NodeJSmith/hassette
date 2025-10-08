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
    from hassette import Hassette, TaskBucket
    from hassette.types import JobCallable, TriggerProtocol


class Scheduler(Resource):
    def __init__(
        self,
        hassette: "Hassette",
        owner: str,
        unique_name_prefix: str | None = None,
        task_bucket: "TaskBucket | None" = None,
    ) -> None:
        """Initialize the Scheduler instance.

        Args:
            hassette (Hassette): The main Hassette instance.
            owner (str): Unique identifier for the owner of the scheduler.
            unique_name_prefix (str | None, optional): Optional unique name prefix.
            task_bucket (TaskBucket | None, optional): Optional task bucket for scheduling tasks.
        """
        super().__init__(hassette, unique_name_prefix=unique_name_prefix, task_bucket=task_bucket)
        self.logger.setLevel(self.hassette.config.scheduler_service_log_level)

        self.owner = owner
        """Owner of the scheduler, must be a unique identifier for the owner."""

        self.mark_ready(reason="Scheduler initialized")

    @property
    def scheduler_service(self) -> _SchedulerService:
        """Get the internal scheduler instance."""
        return self.hassette._scheduler_service

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
        return self.scheduler_service.remove_jobs_by_owner(self.owner)

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
            owner=self.owner,
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
