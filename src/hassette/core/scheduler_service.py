import asyncio
import heapq
import typing
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from fair_async_rlock import FairAsyncRLock
from whenever import TimeDelta, ZonedDateTime

from hassette.core.commands import ExecuteJob
from hassette.core.registration import ScheduledJobRegistration
from hassette.resources.base import Resource, Service
from hassette.scheduler.classes import CronTrigger, IntervalTrigger
from hassette.utils.date_utils import now
from hassette.utils.serialization import safe_json_serialize
from hassette.utils.source_capture import capture_registration_source

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.core.command_executor import CommandExecutor
    from hassette.scheduler.classes import ScheduledJob


T = TypeVar("T")


class SchedulerService(Service):
    """Service that manages scheduled jobs."""

    _job_queue: "_ScheduledJobQueue"
    """Queue of scheduled jobs."""

    _wakeup_event: asyncio.Event
    """Event to wake the scheduler when a new job is added or jobs are removed."""

    _exit_event: asyncio.Event
    """Event to signal the scheduler to exit."""

    _executor: "CommandExecutor"
    """Command executor for running jobs and persisting registration/execution records."""

    def __init__(self, hassette: "Hassette", *, executor: "CommandExecutor", parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._executor = executor
        self._job_queue = self.add_child(_ScheduledJobQueue)
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

    @property
    def config_log_level(self) -> str:
        """Return the log level from the config for this resource."""
        return self.hassette.config.scheduler_service_log_level

    async def before_initialize(self) -> None:
        self.logger.debug("Waiting for Hassette ready event")
        await self.hassette.ready_event.wait()

    async def serve(self) -> None:
        """Run the scheduler forever, processing jobs as they become due."""

        self.mark_ready(reason="Scheduler started")

        while True:
            if self.shutdown_event.is_set():
                self.mark_not_ready(reason="Hassette is shutting down")
                self.logger.debug("Scheduler exiting")
                return

            due_jobs, next_run_time = await self._job_queue.pop_due_and_peek_next(now())

            if due_jobs:
                for job in due_jobs:
                    self.task_bucket.spawn(self._dispatch_and_log(job), name="scheduler:dispatch_scheduled_job")

            await self.sleep(next_run_time)

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

    async def sleep(self, next_run_time: ZonedDateTime | None = None):
        """Sleep until the next job is due or a kick is received.

        This method will wait for the next job to be due or until a kick is received.
        If a kick is received, it will wake up immediately.

        Args:
            next_run_time: Pre-fetched next run time to avoid an extra lock acquisition.
                If None, uses the default delay.
        """
        try:
            timeout = self._calculate_sleep_time(next_run_time).in_seconds()
            await asyncio.wait_for(self._wakeup_event.wait(), timeout=timeout)
            self.logger.debug("Scheduler woke up due to kick")
        except asyncio.CancelledError:
            self.logger.debug("Scheduler sleep cancelled")
            raise
        except TimeoutError:
            self.logger.debug("Scheduler woke up due to timeout")
        finally:
            self._wakeup_event.clear()

    def _calculate_sleep_time(self, next_run_time: ZonedDateTime | None) -> TimeDelta:
        """Calculate the time to sleep until the next job is due.

        Args:
            next_run_time: The next scheduled run time, or None if no jobs are queued.
        """
        if next_run_time is not None:
            self.logger.debug("Next job scheduled at %s", next_run_time)
            delay = max((next_run_time - now()).in_seconds(), self.min_delay)
        else:
            delay = self.default_delay

        delay = min(delay, self.max_delay)
        self.logger.debug("Scheduler sleeping for %s seconds", delay)

        return TimeDelta(seconds=delay)

    def add_job(self, job: "ScheduledJob"):
        """Push a job to the queue and register it with the executor.

        When the job belongs to an app (has app_key), the job is enqueued
        first (so it can be dispatched immediately), then DB registration
        runs in the same task. Until ``db_id`` is set, the dispatch path
        uses direct invocation (no telemetry record).
        """
        if job.app_key:
            return self.task_bucket.spawn(self._enqueue_then_register(job), name="scheduler:add_job")
        return self.task_bucket.spawn(self._enqueue_job(job), name="scheduler:add_job")

    async def _enqueue_then_register(self, job: "ScheduledJob") -> None:
        """Enqueue the job, then register in DB.

        The job is enqueued first so it can be dispatched immediately.
        ``db_id`` is set once DB registration completes; until then, dispatch
        uses the direct-invoke path (no telemetry record).
        """
        source_location, registration_source = capture_registration_source()
        trigger = job.trigger
        if isinstance(trigger, IntervalTrigger):
            trigger_type = "interval"
            trigger_value = str(trigger.interval)
        elif isinstance(trigger, CronTrigger):
            trigger_type = "cron"
            trigger_value = str(trigger.cron_expression)
        else:
            trigger_type = None
            trigger_value = None
        reg = ScheduledJobRegistration(
            app_key=job.app_key,
            instance_index=job.instance_index,
            job_name=job.name,
            handler_method=getattr(job.job, "__qualname__", str(job.job)),
            trigger_type=trigger_type,
            trigger_value=trigger_value,
            repeat=job.repeat,
            args_json=safe_json_serialize(list(job.args)),
            kwargs_json=safe_json_serialize(job.kwargs),
            source_location=source_location,
            registration_source=registration_source,
        )
        await self._enqueue_job(job)
        job.mark_registered(await self._executor.register_job(reg))

    async def _dispatch_and_log(self, job: "ScheduledJob"):
        """Dispatch a job and log its execution.

        Args:
            job: The job to dispatch.
        """
        if job.cancelled:
            self.logger.debug("Job %s is cancelled, skipping dispatch", job)
            return

        self.logger.debug("Dispatching job: %s", job)

        # Run inline — no extra spawn/yield before execution
        try:
            await self.run_job(job)
        except asyncio.CancelledError:
            self.logger.debug("Dispatch cancelled for job %s", job)
            raise

        # Always reschedule after completion, even if the job failed
        try:
            await self.reschedule_job(job)
        except asyncio.CancelledError:
            self.logger.debug("Reschedule cancelled for job %s", job)
            raise
        except Exception:
            self.logger.exception("Error rescheduling job %s", job)

    async def run_job(self, job: "ScheduledJob") -> None:
        """Run a scheduled job by delegating to the CommandExecutor.

        Args:
            job: The job to run.
        """
        if job.cancelled:
            self.logger.debug("Job %s is cancelled, skipping", job)
            await self._remove_job(job)
            return

        run_at_delta = job.next_run - now()
        if run_at_delta.in_seconds() < -self.hassette.config.scheduler_behind_schedule_threshold_seconds:
            self.logger.warning(
                "Job %s is behind schedule by %s seconds, running now.", job, abs(run_at_delta.in_seconds())
            )

        async_fn = self.task_bucket.make_async_adapter(job.job)

        async def _bound_callable() -> None:
            await async_fn(*job.args, **job.kwargs)

        if job.db_id is None:
            # Internal job — run directly without telemetry record
            try:
                await _bound_callable()
            except Exception:
                self.logger.exception("Internal job error (job=%r)", job)
            return
        cmd = ExecuteJob(
            job=job,
            callable=_bound_callable,
            job_db_id=job.db_id,
        )
        await self._executor.execute(cmd)

    async def reschedule_job(self, job: "ScheduledJob"):
        """Reschedule a job if it is repeating.

        Args:
            job: The job to reschedule.
        """

        if job.cancelled:
            self.logger.debug("Job %s is cancelled, not rescheduling", job)
            await self._remove_job(job)
            return

        if job.repeat and job.trigger:
            curr_next_run = job.next_run
            next_run = job.trigger.next_run_time(job.next_run, now())
            job.set_next_run(next_run)
            next_run_time_delta = job.next_run - curr_next_run
            secs = next_run_time_delta.in_seconds()
            if secs <= 0:
                self.logger.warning("Trigger produced non-future next_run (delta=%ss), advancing by 1s", secs)
                job.set_next_run(curr_next_run.add(seconds=1))

            self.logger.debug(
                "Rescheduling repeating job %s from %s to %s (%s)",
                job,
                curr_next_run,
                job.next_run,
                next_run_time_delta.in_seconds(),
            )
            await self._enqueue_job(job)
            return

        # One-time job, remove it
        await self._remove_job(job)

    async def get_all_jobs(self) -> list["ScheduledJob"]:
        """Return all currently scheduled jobs across all apps."""
        return await self._job_queue.get_all()

    def remove_jobs_by_owner(self, owner: str) -> asyncio.Task:
        """Remove all jobs for a given owner.

        Args:
            owner: The owner of the jobs to remove.
        """

        return self.task_bucket.spawn(self._remove_jobs_by_owner(owner), name="scheduler:remove_jobs_by_owner")

    def remove_job(self, job: "ScheduledJob") -> asyncio.Task:
        """Remove a job from the scheduler.

        Args:
            job: The job to remove.
        """
        return self.task_bucket.spawn(self._remove_job(job), name="scheduler:remove_job")


class _ScheduledJobQueue(Resource):
    """Encapsulates the scheduler heap with fair locking semantics."""

    _lock: FairAsyncRLock
    """Lock to protect access to the queue."""

    _queue: "HeapQueue[ScheduledJob]"
    """The heap queue of scheduled jobs."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._lock = FairAsyncRLock()
        self._queue = HeapQueue()
        self.mark_ready(reason="Queue ready")

    @property
    def config_log_level(self) -> str:
        """Return the log level from the config for this resource."""
        return self.hassette.config.scheduler_service_log_level

    async def add(self, job: "ScheduledJob") -> None:
        """Add a job to the queue."""

        async with self._lock:
            self._queue.push(job)

        self.logger.debug("Queued job %s for %s", job, job.next_run)

    async def pop_due(self, reference_time: ZonedDateTime | None = None) -> list["ScheduledJob"]:
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

    async def pop_due_and_peek_next(
        self, reference_time: ZonedDateTime
    ) -> tuple[list["ScheduledJob"], ZonedDateTime | None]:
        """Pop all due jobs and return the next run time in a single lock acquisition."""

        due_jobs: list[ScheduledJob] = []

        async with self._lock:
            current_time = reference_time
            while not self._queue.is_empty():
                candidate = self._queue.peek()
                if candidate is None or candidate.next_run > current_time:
                    break

                due_jobs.append(self._queue.pop())
                current_time = now()

            upcoming = self._queue.peek()
            next_run = upcoming.next_run if upcoming else None

        if due_jobs:
            self.logger.debug("Dequeued %d due jobs", len(due_jobs))

        return due_jobs, next_run

    async def next_run_time(self) -> ZonedDateTime | None:
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
            removed = self._queue.remove_where(lambda job: job.owner_id == owner)

        if removed:
            self.logger.debug("Removed %d jobs for owner '%s'", removed, owner)
            return removed

        self.logger.debug("No jobs found for owner '%s' to remove", owner)
        return removed

    async def remove_job(self, job: "ScheduledJob") -> bool:
        """Remove a specific job if it exists."""

        async with self._lock:
            removed = self._queue.remove_item(job)

        if removed:
            self.logger.debug("Removed job: %s", job)
            return removed

        self.logger.debug("Job not found in queue, cannot remove: %s", job)
        return removed

    async def get_all(self) -> list["ScheduledJob"]:
        """Return a snapshot of all queued jobs (non-destructive)."""
        async with self._lock:
            return list(self._queue)

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

    def __iter__(self) -> Iterator[T]:
        """Iterate over all items in the queue (unordered)."""
        return iter(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

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
            The next job in the queue.

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
