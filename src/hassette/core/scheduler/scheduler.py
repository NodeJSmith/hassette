import asyncio
import contextlib
import heapq
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from whenever import SystemDateTime, TimeDelta

from hassette.async_utils import make_async_adapter
from hassette.core.classes import Resource, Service
from hassette.core.types import TriggerProtocol

from .triggers import CronTrigger, IntervalTrigger, now

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


T = TypeVar("T")


class _Scheduler(Service):
    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)

        self.min_delay = 0.1
        self.max_delay = 30.0

        self._queue: HeapQueue[ScheduledJob] = HeapQueue()
        self._counter = 0
        self._wakeup_event = asyncio.Event()
        self._exit_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self):
        """Run the scheduler forever, processing jobs as they become due."""
        try:
            await self.handle_start()
            self._exit_event = asyncio.Event()

            while True:
                if self._exit_event.is_set():
                    self.logger.debug("Scheduler exiting")
                    return

                while not self._queue.is_empty() and (peek := self._queue.peek()) and peek.next_run <= now():
                    job = self._queue.pop()
                    self._tasks.add(self.hassette.create_task(self._dispatch_and_log(job)))

                await self._sleep()
        except asyncio.CancelledError:
            self.logger.debug("Scheduler cancelled, stopping")
            await self.handle_stop()
            self._exit_event.set()
        except Exception as e:
            await self.handle_crash(e)
            self._exit_event.set()
            raise
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        """Cleanup resources after the WebSocket connection is closed."""

        # Cancel background tasks
        if self._tasks:
            for task in list(self._tasks):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self.logger.debug("Cancelled %d pending tasks", len(self._tasks))

    def _kick(self):
        """Wake up the scheduler to check for jobs."""
        self._wakeup_event.set()

    async def _sleep(self):
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
            delay = 15.0  # or some generous default

        # ensure delay isn't over N seconds
        delay = min(delay, self.max_delay)

        self.logger.debug("Scheduler sleeping for %s seconds", delay)

        return TimeDelta(seconds=delay)

    def _push_job(self, job: "ScheduledJob"):
        """Push a job to the queue."""
        self._queue.push(job)
        self._kick()
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
        with contextlib.suppress(Exception):
            await self._run_job(job)

        try:
            await self._reschedule_job(job)
        except Exception:
            self.logger.exception("Error rescheduling job %s", job)

    async def _reschedule_job(self, job: "ScheduledJob"):
        """Reschedule a job if it is repeating.

        Args:
            job (ScheduledJob): The job to reschedule.
        """

        if job.cancelled:
            self.logger.debug("Job %s is cancelled, not rescheduling", job)
            return

        if job.repeat and job.trigger:
            curr_next_run = job.next_run
            job.next_run = job.trigger.next_run_time()
            next_run_time_delta = job.next_run - curr_next_run
            assert next_run_time_delta.in_seconds() > 0, "Next run time must be in the future"

            self.logger.debug(
                "Rescheduling repeating job %s from %s to %s (%s)",
                job,
                curr_next_run,
                job.next_run,
                next_run_time_delta.in_seconds(),
            )
            self._push_job(job)

    async def _run_job(self, job: "ScheduledJob"):
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
            await async_func()
        except Exception as e:
            self.logger.error("Error running job%s: %s - %s", job, type(e), e)


class Scheduler(Resource):
    def __init__(self, hassette: "Hassette", _scheduler: _Scheduler) -> None:
        super().__init__(hassette)
        self._scheduler = _scheduler

    @property
    def scheduler(self) -> _Scheduler:
        """Get the internal scheduler instance."""
        return self._scheduler

    def add_job(self, job: "ScheduledJob") -> "ScheduledJob":
        """Add a job to the scheduler.

        Args:
            job (ScheduledJob): The job to add.

        Returns:
            ScheduledJob: The added job.
        """

        if not isinstance(job, ScheduledJob):
            raise TypeError(f"Expected ScheduledJob, got {type(job).__name__}")

        self._scheduler._push_job(job)

        return job

    def schedule(
        self,
        func: Callable[[], Awaitable[None]] | Callable[[], None],
        run_at: SystemDateTime,
        trigger: TriggerProtocol | None = None,
        repeat: bool = False,
        name: str = "",
    ) -> "ScheduledJob":
        """Schedule a job to run at a specific time or based on a trigger.

        Args:
            func (Callable): The function to run.
            run_at (SystemDateTime): The time to run the job.
            trigger (TriggerProtocol | None): Optional trigger for repeating jobs.
            repeat (bool): Whether the job should repeat.
            name (str): Optional name for the job.

        Returns:
            ScheduledJob: The scheduled job.
        """

        job = ScheduledJob(next_run=run_at, job=func, trigger=trigger, repeat=repeat, name=name)
        return self.add_job(job)

    def run_once(
        self,
        func: Callable[[], Awaitable[None]] | Callable[[], None],
        run_at: SystemDateTime,
        name: str = "",
    ) -> "ScheduledJob":
        """Schedule a job to run at a specific time.

        Args:
            func (Callable): The function to run.
            run_at (SystemDateTime): The time to run the job.
            name (str): Optional name for the job.

        Returns:
            ScheduledJob: The scheduled job.
        """

        return self.schedule(func, run_at, name=name)

    def run_every(
        self,
        func: Callable[[], Awaitable[None]] | Callable[[], None],
        interval: TimeDelta | float,
        name: str = "",
        start: SystemDateTime | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run at a fixed interval.

        Args:
            func (Callable): The function to run.
            interval (TimeDelta | float): The interval between runs.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the interval.

        Returns:
            ScheduledJob: The scheduled job.
        """

        interval_seconds = interval if isinstance(interval, float | int) else interval.in_seconds()

        first_run = start if start else now().add(seconds=interval_seconds)
        trigger = IntervalTrigger.from_arguments(seconds=interval_seconds, start=first_run)

        return self.schedule(func, first_run, trigger=trigger, repeat=True, name=name)

    def run_in(
        self,
        func: Callable[[], Awaitable[None]] | Callable[[], None | Any],
        delay: TimeDelta | float,
        name: str = "",
        start: SystemDateTime | None = None,
    ) -> "ScheduledJob":
        """Schedule a job to run after a delay.

        Args:
            func (Callable): The function to run.
            delay (TimeDelta | float): The delay before running the job.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the delay.

        Returns:
            ScheduledJob: The scheduled job.
        """

        delay_seconds = delay if isinstance(delay, float | int) else delay.in_seconds()

        run_at = start if start else now().add(seconds=delay_seconds)
        return self.schedule(func, run_at, name=name)

    def run_cron(
        self,
        func: Callable[[], Awaitable[None]] | Callable[[], None],
        second: int | str = 0,
        minute: int | str = 0,
        hour: int | str = 0,
        day_of_month: int | str = "*",
        month: int | str = "*",
        day_of_week: int | str = "*",
        name: str = "",
        start: SystemDateTime | None = None,
    ) -> "ScheduledJob":
        """Schedule a job using a cron expression.

        Uses a 6-field format (seconds, minutes, hours, day of month, month, day of week).

        Args:
            func (Callable): The function to run.
            second (int | str): Seconds field of the cron expression.
            minute (int | str): Minutes field of the cron expression.
            hour (int | str): Hours field of the cron expression.
            day_of_month (int | str): Day of month field of the cron expression.
            month (int | str): Month field of the cron expression.
            day_of_week (int | str): Day of week field of the cron expression.
            name (str): Optional name for the job.
            start (SystemDateTime | None): Optional start time for the first run. If provided the job will run at this\
                time. Otherwise it will run at the current time plus the cron schedule.

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
        return self.schedule(func, run_at, trigger=trigger, repeat=True, name=name)


@dataclass(order=True)
class ScheduledJob:
    """A job scheduled to run based on a trigger or at a specific time."""

    next_run: SystemDateTime
    job: Callable[[], Awaitable[None]] | Callable[[], None] = field(compare=False)
    trigger: TriggerProtocol | None = field(compare=False, default=None)
    repeat: bool = field(compare=False, default=False)
    name: str = field(default="", compare=False)
    cancelled: bool = field(default=False, compare=False)

    def __repr__(self) -> str:
        return f"ScheduledJob(name={self.name!r}, next_run={self.next_run})"

    def __post_init__(self):
        self.next_run = self.next_run.round(unit="second")

        if not self.name:
            self.name = self.job.__name__ if hasattr(self.job, "__name__") else str(self.job)

    def cancel(self) -> None:
        """Cancel the scheduled job by setting the cancelled flag to True."""
        self.cancelled = True


@dataclass
class HeapQueue(Generic[T]):
    _queue: list[T] = field(default_factory=list)

    def push(self, job: T):
        """Push a job onto the queue."""
        heapq.heappush(self._queue, job)

    def pop(self) -> T:
        """Pop the next job from the queue."""
        return heapq.heappop(self._queue)

    def peek(self) -> T | None:
        """Peek at the next job without removing it.

        Returns:
            T | None: The next job in the queue, or None if the queue is empty"""
        return self._queue[0] if self._queue else None

    def peek_or_raise(self) -> T:
        """Peek at the next job without removing it, raising an error if the queue is empty.

        Method that the type checker knows always return a value - call `is_empty` first to avoid exceptions.

        Returns:
            T: The next job in the queue.

        Raises:
            IndexError: If the queue is empty.

        """
        if not self._queue:
            raise IndexError("Peek from an empty queue")
        return cast("T", self.peek())

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return not self._queue
