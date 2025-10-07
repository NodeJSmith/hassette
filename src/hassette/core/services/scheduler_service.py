import asyncio
import heapq
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from fair_async_rlock import FairAsyncRLock
from whenever import SystemDateTime, TimeDelta

from hassette.core.resources.base import Resource, Service
from hassette.utils.async_utils import make_async_adapter
from hassette.utils.date_utils import now

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.resources.scheduler.classes import ScheduledJob


T = TypeVar("T")


class _SchedulerService(Service):  # pyright: ignore[reportUnusedClass]
    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.scheduler_service_log_level)
        self._job_queue = _ScheduledJobQueue(hassette)
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
                if self._exit_event.is_set() or self.hassette.shutdown_event.is_set():
                    self.mark_not_ready(reason="Hassette is shutting down")
                    self.logger.debug("Scheduler exiting")
                    return

                due_jobs = await self._job_queue.pop_due(now())

                if due_jobs:
                    for job in due_jobs:
                        self.task_bucket.spawn(
                            self._dispatch_and_log(job),
                            name="scheduler:dispatch_scheduled_job",
                        )
                    continue

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
            await self.cleanup()

    def kick(self):
        """Wake up the scheduler to check for jobs."""
        self._wakeup_event.set()

    async def _enqueue_job(self, job: "ScheduledJob") -> None:
        """Push a job onto the queue and wake the scheduler."""

        await self._job_queue.add(job)
        self.kick()

    async def _remove_jobs_by_owner(self, owner: str) -> None:
        """Remove all jobs for an owner and wake the scheduler if necessary."""

        removed = await self._job_queue.remove_owner(owner)

        if removed:
            self.kick()

    async def _remove_job(self, job: "ScheduledJob") -> None:
        """Remove a specific job and wake the scheduler if successful."""

        removed = await self._job_queue.remove_job(job)

        if removed:
            self.kick()

    async def sleep(self):
        """Sleep until the next job is due or a kick is received.

        This method will wait for the next job to be due or until a kick is received.
        If a kick is received, it will wake up immediately.
        """
        try:
            timeout = (await self._get_sleep_time()).in_seconds()
            await asyncio.wait_for(self._wakeup_event.wait(), timeout=timeout)
            self.logger.debug("Scheduler woke up due to kick")
        except asyncio.CancelledError:
            self.logger.debug("Scheduler sleep cancelled")
            raise
        except TimeoutError:
            self.logger.debug("Scheduler woke up due to timeout")
        finally:
            self._wakeup_event.clear()

    async def _get_sleep_time(self) -> TimeDelta:
        """Get the time to sleep until the next job is due.
        If there are no jobs, return a default sleep time.
        """
        next_run_time = await self._job_queue.next_run_time()

        if next_run_time is not None:
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
        self.task_bucket.spawn(self._enqueue_job(job), name="scheduler:add_job")

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
            await self._enqueue_job(job)

    def remove_jobs_by_owner(self, owner: str) -> None:
        """Remove all jobs for a given owner.

        Args:
            owner (str): The owner of the jobs to remove.
        """

        self.task_bucket.spawn(
            self._remove_jobs_by_owner(owner),
            name="scheduler:remove_jobs_by_owner",
        )

    def remove_job(self, job: "ScheduledJob") -> None:
        """Remove a job from the scheduler.

        Args:
            job (ScheduledJob): The job to remove.
        """
        self.task_bucket.spawn(self._remove_job(job), name="scheduler:remove_job")


class _ScheduledJobQueue(Resource):
    """Encapsulates the scheduler heap with fair locking semantics."""

    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.scheduler_service_log_level)

        self._lock = FairAsyncRLock()
        self._queue: HeapQueue[ScheduledJob] = HeapQueue()

        self.mark_ready(reason="Queue ready")

    async def add(self, job: "ScheduledJob") -> None:
        """Add a job to the queue."""

        async with self._lock:
            self._queue.push(job)

        self.logger.debug("Queued job %s for %s", job, job.next_run)

    async def pop_due(self, reference_time: SystemDateTime | None = None) -> list["ScheduledJob"]:
        """Return and remove all jobs due to run at or before the reference time."""

        due_jobs: list[ScheduledJob] = []

        async with self._lock:
            current_time = reference_time or now()
            while not self._queue.is_empty():
                candidate = self._queue.peek()
                if candidate is None or candidate.next_run > current_time:
                    break

                due_jobs.append(self._queue.pop())
                current_time = now()

        if due_jobs:
            self.logger.debug("Dequeued %d due jobs", len(due_jobs))

        return due_jobs

    async def next_run_time(self) -> SystemDateTime | None:
        """Return the next scheduled run time if available."""

        async with self._lock:
            upcoming = self._queue.peek()
            return upcoming.next_run if upcoming else None

    async def peek(self) -> "ScheduledJob | None":
        """Return the next scheduled job without removing it."""

        async with self._lock:
            return self._queue.peek()

    async def remove_owner(self, owner: str) -> int:
        """Remove all jobs belonging to the given owner."""

        async with self._lock:
            removed = self._queue.remove_where(lambda job: job.owner == owner)

        if removed:
            self.logger.debug("Removed %d jobs for owner '%s'", removed, owner)
        else:
            self.logger.debug("No jobs found for owner '%s' to remove", owner)

        return removed

    async def remove_job(self, job: "ScheduledJob") -> bool:
        """Remove a specific job if it exists."""

        async with self._lock:
            removed = self._queue.remove_item(job)

        if removed:
            self.logger.debug("Removed job: %s", job)
        else:
            self.logger.debug("Job not found in queue, cannot remove: %s", job)

        return removed

    async def clear(self, predicate: Callable[["ScheduledJob"], bool] | None = None) -> int:
        """Clear the queue, optionally filtering by predicate."""

        def is_true(_: Any) -> bool:
            return True

        if predicate is None:
            predicate = is_true

        async with self._lock:
            removed = self._queue.remove_where(predicate)

        if removed:
            self.logger.debug("Cleared %d jobs from queue", removed)

        return removed


@dataclass
class HeapQueue(Generic[T]):
    _queue: list[T] = field(default_factory=list)

    def push(self, job: T):
        """Push a job onto the queue."""
        heapq.heappush(self._queue, job)  # pyright: ignore[reportArgumentType]

    def pop(self) -> T:
        """Pop the next job from the queue."""
        return heapq.heappop(self._queue)  # pyright: ignore[reportArgumentType]

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

    def remove_where(self, predicate: Callable[[T], bool]) -> int:
        """Remove all items matching the predicate, returning the number removed."""

        original_length = len(self._queue)
        if not original_length:
            return 0

        self._queue = [job for job in self._queue if not predicate(job)]
        removed = original_length - len(self._queue)

        if removed:
            heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]

        return removed

    def remove_item(self, item: T) -> bool:
        """Remove a specific item from the queue if present."""

        if item not in self._queue:
            return False

        self._queue.remove(item)
        heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]
        return True
