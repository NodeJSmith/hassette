import asyncio
import heapq
import typing
from collections.abc import Mapping
from typing import Any, TypeVar

from whenever import SystemDateTime, TimeDelta

from hassette.async_utils import make_async_adapter
from hassette.core.classes.resource import Resource, Service

from .classes import HeapQueue, ScheduledJob
from .triggers import CronTrigger, IntervalTrigger, now

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette
    from hassette.core.types import JobCallable, TriggerProtocol

T = TypeVar("T")


class _SchedulerService(Service):
    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.scheduler_service_log_level)

        self.lock = asyncio.Lock()
        self._queue: HeapQueue[ScheduledJob] = HeapQueue()
        self._wakeup_event = asyncio.Event()
        self._exit_event = asyncio.Event()

    @property
    def min_delay(self) -> float:
        return self.hassette.config.scheduler_min_delay_seconds

    @property
    def max_delay(self) -> float:
        return self.hassette.config.scheduler_max_delay_seconds

    @property
    def default_delay(self) -> float:
        return self.hassette.config.scheduler_default_delay_seconds

    async def run_forever(self):
        """Run the scheduler forever, processing jobs as they become due."""

        async with self.starting():
            self.logger.debug("Waiting for Hassette ready event")
            await self.hassette.ready_event.wait()
            self.mark_ready(reason="Hassette is ready")

        try:
            self._exit_event = asyncio.Event()

            while True:
                if self._exit_event.is_set():
                    self.logger.debug("Scheduler exiting")
                    return

                while not self._queue.is_empty() and (peek := self._queue.peek()) and peek.next_run <= now():
                    job = self._queue.pop()
                    self.task_bucket.spawn(self._dispatch_and_log(job), name="scheduler:dispatch_scheduled_job")

                await self.sleep()
        except asyncio.CancelledError:
            self.mark_not_ready(reason="Scheduler cancelled")
            self.logger.debug("Scheduler cancelled, stopping")
            await self.handle_stop()
            self._exit_event.set()
        except Exception as e:
            await self.handle_crash(e)
            self._exit_event.set()
            raise
        finally:
            await self._cleanup()

    def kick(self):
        """Wake up the scheduler to check for jobs."""
        self._wakeup_event.set()

    async def sleep(self):
        """Sleep until the next job is due or a kick is received.

        This method will wait for the next job to be due or until a kick is received.
        If a kick is received, it will wake up immediately.
        """
        try:
            await asyncio.wait_for(self._wakeup_event.wait(), timeout=self._get_sleep_time().in_seconds())
            self.logger.debug("Scheduler woke up due to kick")
        except asyncio.CancelledError:
            self.logger.debug("Scheduler sleep cancelled")
            raise
        except TimeoutError:
            self.logger.debug("Scheduler woke up due to timeout")
        finally:
            self._wakeup_event.clear()

    def _get_sleep_time(self) -> TimeDelta:
        """Get the time to sleep until the next job is due.
        If there are no jobs, return a default sleep time.
        """
        if not self._queue.is_empty():
            next_run_time = self._queue.peek_or_raise().next_run
            self.logger.debug("Next job scheduled at %s", next_run_time)
            delay = max((next_run_time - now()).in_seconds(), self.min_delay)
        else:
            delay = self.default_delay

        # ensure delay isn't over N seconds
        delay = min(delay, self.max_delay)

        self.logger.debug("Scheduler sleeping for %s seconds", delay)

        return TimeDelta(seconds=delay)

    def add_job(self, job: "ScheduledJob"):
        """Push a job to the queue."""
        self._queue.push(job)
        self.kick()
        self.logger.debug("Scheduled job: %s", job)

    async def _dispatch_and_log(self, job: "ScheduledJob"):
        """Dispatch a job and log its execution.

        Args:
            job (ScheduledJob): The job to dispatch.
        """
        if job.cancelled:
            self.logger.debug("Job %s is cancelled, skipping dispatch", job)
            return

        self.logger.debug("Dispatching job: %s", job)
        try:
            await self.run_job(job)
        except asyncio.CancelledError:
            self.logger.debug("Dispatch cancelled for job %s", job)
            raise

        try:
            await self.reschedule_job(job)
        except asyncio.CancelledError:
            self.logger.debug("Reschedule cancelled for job %s", job)
            raise
        except Exception:
            self.logger.exception("Error rescheduling job %s", job)

    async def run_job(self, job: "ScheduledJob"):
        """Run a scheduled job.

        Args:
            job (ScheduledJob): The job to run.
        """

        if job.cancelled:
            self.logger.debug("Job %s is cancelled, skipping", job)
            return

        func = job.job

        run_at_delta = job.next_run - now()
        if run_at_delta.in_seconds() < -1:
            self.logger.warning(
                "Job %s is behind schedule by %s seconds, running now.",
                job,
                abs(run_at_delta.in_seconds()),
            )

        try:
            self.logger.debug("Running job %s at %s", job, now())
            async_func = make_async_adapter(func)
            await async_func(*job.args, **job.kwargs)
        except asyncio.CancelledError:
            self.logger.debug("Execution cancelled for job %s", job)
            raise
        except Exception:
            self.logger.exception("Error running job %s", job)

    async def reschedule_job(self, job: "ScheduledJob"):
        """Reschedule a job if it is repeating.

        Args:
            job (ScheduledJob): The job to reschedule.
        """

        if job.cancelled:
            self.logger.debug("Job %s is cancelled, not rescheduling", job)
            return

        if job.repeat and job.trigger:
            curr_next_run = job.next_run
            next_run = job.trigger.next_run_time()
            job.set_next_run(next_run)
            next_run_time_delta = job.next_run - curr_next_run
            assert next_run_time_delta.in_seconds() > 0, "Next run time must be in the future"

            self.logger.debug(
                "Rescheduling repeating job %s from %s to %s (%s)",
                job,
                curr_next_run,
                job.next_run,
                next_run_time_delta.in_seconds(),
            )
            self.add_job(job)

    def remove_jobs_by_owner(self, owner: str) -> None:
        """Remove all jobs for a given owner.

        Args:
            owner (str): The owner of the jobs to remove.
        """
        original_count = len(self._queue._queue)
        self._queue._queue = [job for job in self._queue._queue if job.owner != owner]
        removed_count = original_count - len(self._queue._queue)

        if removed_count > 0:
            heapq.heapify(self._queue._queue)
            self.kick()
            self.logger.debug("Removed %d jobs for owner '%s'", removed_count, owner)
        else:
            self.logger.debug("No jobs found for owner '%s' to remove", owner)

    def remove_job(self, job: "ScheduledJob") -> None:
        """Remove a job from the scheduler.

        Args:
            job (ScheduledJob): The job to remove.
        """
        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")

        if job in self._queue._queue:
            self._queue._queue.remove(job)
            heapq.heapify(self._queue._queue)
            self.kick()
            self.logger.debug("Removed job: %s", job)
        else:
            self.logger.debug("Job not found in queue, cannot remove: %s", job)


class Scheduler(Resource):
    def __init__(self, hassette: "Hassette", owner: str) -> None:
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.scheduler_service_log_level)

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

    def remove_job(self, job: "ScheduledJob") -> None:
        """Remove a job from the scheduler.

        Args:
            job (ScheduledJob): The job to remove.
        """

        self.scheduler_service.remove_job(job)

    def remove_all_jobs(self) -> None:
        """Remove all jobs for the owner of this scheduler."""
        self.scheduler_service.remove_jobs_by_owner(self.owner)

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
