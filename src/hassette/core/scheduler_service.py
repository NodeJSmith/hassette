import asyncio
import heapq
import random
import typing
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast

from fair_async_rlock import FairAsyncRLock
from whenever import TimeDelta, ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.commands import ExecuteJob
from hassette.core.registration import ScheduledJobRegistration
from hassette.core.registration_tracker import RegistrationTracker
from hassette.resources.base import Resource, Service
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.serialization import safe_json_serialize

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

    _reg_tracker: RegistrationTracker
    """Tracks pending DB registration tasks per app_key for await barrier support."""

    @property
    def _pending_registration_tasks(self) -> dict[str, list[asyncio.Task[None]]]:
        """Backward-compatible access to the registration tracker's internal tasks dict."""
        return self._reg_tracker._tasks

    @_pending_registration_tasks.setter
    def _pending_registration_tasks(self, value: dict[str, list[asyncio.Task[None]]]) -> None:
        """Allow direct assignment for tests that bypass __init__."""
        if not hasattr(self, "_reg_tracker"):
            self._reg_tracker = RegistrationTracker()
        self._reg_tracker._tasks = value

    _removal_callbacks: dict[str, Callable[["ScheduledJob"], None]]
    """Per-owner callbacks invoked whenever a job is removed via dequeue_job() or _remove_job()."""

    def __init__(self, hassette: "Hassette", *, executor: "CommandExecutor", parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._executor = executor
        self._job_queue = self.add_child(_ScheduledJobQueue)
        self._wakeup_event = asyncio.Event()
        self._exit_event = asyncio.Event()
        self._reg_tracker = RegistrationTracker()
        self._removal_callbacks = {}

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
    def config_log_level(self) -> LOG_LEVEL_TYPE:
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

            due_jobs, next_run_time = await self._job_queue.pop_due_and_peek_next(date_utils.now())

            if due_jobs:
                for job in due_jobs:
                    self.task_bucket.spawn(self._dispatch_and_log(job), name="scheduler:dispatch_scheduled_job")

            await self.sleep(next_run_time)

    def kick(self):
        """Wake up the scheduler to check for jobs."""
        self._wakeup_event.set()

    async def _enqueue_job(self, job: "ScheduledJob") -> None:
        """Push a job onto the queue and wake the scheduler."""

        self._apply_jitter_to_heap(job)
        await self._job_queue.add(job)
        self.kick()

    async def _remove_jobs_by_owner(self, owner: str) -> None:
        """Remove all jobs for an owner and wake the scheduler if necessary."""

        removed = await self._job_queue.remove_owner(owner)

        if removed:
            self.kick()
            self._fire_removal_callbacks(removed)

    def register_removal_callback(self, owner_id: str, callback: Callable[["ScheduledJob"], None]) -> None:
        """Register a callback to be called whenever a job belonging to owner_id is removed.

        If a callback is already registered for owner_id, the new callback replaces it.
        This handles legitimate re-registration during hot-reload cycles where the old
        Scheduler instance is orphaned without a formal shutdown.

        Args:
            owner_id: The owner whose job removals should trigger the callback.
            callback: Called with the removed ScheduledJob as its single argument.
        """
        self._removal_callbacks[owner_id] = callback

    def deregister_removal_callback(self, owner_id: str) -> None:
        """Remove the removal callback for owner_id, if any.

        No-op when owner_id has no registered callback. Called by
        ``Scheduler.on_shutdown`` so the slot is freed before the Scheduler
        is re-initialized (e.g. during a hot-reload cycle).

        Args:
            owner_id: The owner whose callback should be removed.
        """
        self._removal_callbacks.pop(owner_id, None)

    def _fire_removal_callbacks(self, jobs: "list[ScheduledJob]") -> None:
        """Invoke per-owner removal callbacks for each job in jobs."""
        for job in jobs:
            callback = self._removal_callbacks.get(job.owner_id)
            if callback is not None:
                callback(job)

    def _apply_jitter_to_heap(self, job: "ScheduledJob") -> None:
        """Apply jitter to the heap sort_index and fire_at without mutating job.next_run.

        If job.jitter is not None, a random offset in [0, jitter) seconds is added
        to ``job.fire_at`` and ``job.sort_index``. ``job.next_run`` is never modified
        — it is the unjittered logical fire time used as ``previous_run`` in subsequent
        trigger calls. When jitter is None or 0, ``fire_at`` equals ``next_run`` exactly
        (already set by ``set_next_run``).

        Args:
            job: The job whose sort_index and fire_at should be jittered.
        """
        if job.jitter is not None:
            offset = random.uniform(0, job.jitter)
            jittered_time = job.next_run.add(seconds=offset)
            job.fire_at = jittered_time
            job.sort_index = (jittered_time.timestamp_nanos(), job.job_id)
            self.logger.debug(
                "Applied jitter offset=%.3fs to job %s: next_run=%s → fire_at=%s",
                offset,
                job,
                job.next_run,
                job.fire_at,
            )

    async def _remove_job(self, job: "ScheduledJob") -> None:
        """Remove a specific job via the async path (acquires lock) and wake the scheduler.

        Used by the serve loop for job exhaustion and trigger errors in reschedule_job.
        The callback is fired unconditionally because the serve loop has already
        popped the job from the queue before reschedule_job calls _remove_job —
        remove_job would return False and the callback would silently drop.

        Note: for cancel-initiated removal, use ``dequeue_job`` (synchronous path)
        instead. Both paths fire ``_fire_removal_callbacks`` unconditionally.
        """

        removed = await self._job_queue.remove_job(job)

        if removed:
            self.kick()

        self._fire_removal_callbacks([job])

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
            delay = max((next_run_time - date_utils.now()).in_seconds(), self.min_delay)
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

        Registration tasks are tracked per ``app_key`` so
        ``await_registrations_complete()`` can drain them before reconciliation.
        Completed tasks are pruned from the list on each call to prevent
        unbounded growth for long-lived apps with dynamic job registration.
        """
        if job.app_key:
            task = self.task_bucket.spawn(self._enqueue_then_register(job), name="scheduler:add_job")
            self._reg_tracker.prune_and_track(job.app_key, task)
            return task
        return self.task_bucket.spawn(self._enqueue_job(job), name="scheduler:add_job")

    async def await_registrations_complete(self, app_key: str) -> None:
        """Wait for all pending DB registration tasks for an app to complete.

        Called by ``AppLifecycleService._reconcile_app_registrations()`` before
        reconciliation to ensure all job ``db_id`` values are populated. Tasks
        that error (DB unavailable) complete with ``db_id = None`` — the job is
        excluded from ``live_job_ids`` but not actively retired.

        Has a configurable timeout (``config.registration_await_timeout``, default 30s)
        to prevent indefinite hangs if the DB write queue stalls.

        Args:
            app_key: The app key whose pending registration tasks to await.
        """
        timeout = float(self.hassette.config.registration_await_timeout)
        await self._reg_tracker.await_complete(app_key, timeout=timeout, logger=self.logger)

    async def _enqueue_then_register(self, job: "ScheduledJob") -> None:
        """Enqueue the job, then register in DB.

        The job is enqueued first so it can be dispatched immediately.
        ``db_id`` is set once DB registration completes; until then, dispatch
        produces an orphan execution record with ``job_id=None``.

        Trigger type dispatch uses the TriggerProtocol methods exclusively.
        Non-protocol triggers are rejected synchronously by ``Scheduler.schedule()``
        before reaching this path.
        """
        source_location = job.source_location
        registration_source: str | None = job.registration_source or None
        trigger = job.trigger
        if trigger is not None:
            trigger_type: str | None = trigger.trigger_db_type()
            trigger_label: str = trigger.trigger_label()
            trigger_detail: str | None = trigger.trigger_detail()
        else:
            trigger_type = None
            trigger_label = ""
            trigger_detail = None
        reg = ScheduledJobRegistration(
            app_key=job.app_key,
            instance_index=job.instance_index,
            job_name=job.name,
            handler_method=getattr(job.job, "__qualname__", str(job.job)),
            trigger_type=trigger_type,
            trigger_label=trigger_label,
            trigger_detail=trigger_detail,
            args_json=safe_json_serialize(list(job.args)),
            kwargs_json=safe_json_serialize(job.kwargs),
            source_location=source_location,
            registration_source=registration_source,
            source_tier=job.source_tier,
            group=job.group,
        )
        await self._enqueue_job(job)
        try:
            job.mark_registered(await self._executor.register_job(reg))
        except Exception:
            self.logger.exception(
                "Failed to register job in DB for owner_id=%s name=%s; "
                "job will run without telemetry until next restart",
                job.owner_id,
                job.name,
            )

    async def _dispatch_and_log(self, job: "ScheduledJob"):
        """Dispatch a job and log its execution.

        Args:
            job: The job to dispatch.
        """
        if job._dequeued:
            self.logger.debug("Job %s was dequeued (cancelled between heap-pop and dispatch), skipping", job)
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

        All jobs go through ``ExecuteJob`` regardless of whether ``db_id`` is set.
        When ``db_id`` is ``None`` (job not yet registered), ``ExecuteJob`` is created
        with ``job_db_id=None`` and the ``CommandExecutor`` records an orphan execution row.

        Args:
            job: The job to run.
        """
        lag = (date_utils.now() - job.fire_at).in_seconds()
        if lag > self.hassette.config.scheduler_behind_schedule_threshold_seconds:
            self.logger.warning("Job %s is behind schedule by %.2fs", job, lag)

        async_fn = self.task_bucket.make_async_adapter(job.job)

        async def _bound_callable() -> None:
            await async_fn(*job.args, **job.kwargs)

        # Resolve effective timeout: timeout_disabled → None; job.timeout → use it;
        # job.timeout is None → config default
        if job.timeout_disabled:
            effective_timeout = None
        elif job.timeout is not None:
            effective_timeout = job.timeout
        else:
            effective_timeout = self.hassette.config.scheduler_job_timeout_seconds

        cmd = ExecuteJob(
            job=job,
            callable=_bound_callable,
            job_db_id=job.db_id,
            source_tier=job.source_tier,
            effective_timeout=effective_timeout,
        )
        await self._executor.execute(cmd)

    async def reschedule_job(self, job: "ScheduledJob"):
        """Reschedule a job based on its trigger's next_run_time().

        If the trigger raises or returns None, the job is treated as exhausted and removed. If the trigger
        returns a non-future time (delta ≤ 0), a WARNING is logged and the next run
        is advanced by 1 second. Exceptions from next_run_time() are caught, logged,
        and treated as exhaustion — the scheduler must never crash due to a
        misbehaving trigger.

        Args:
            job: The job to reschedule.
        """

        try:
            next_run = job.trigger.next_run_time(job.next_run, date_utils.now()) if job.trigger else None
        except Exception:
            self.logger.exception(
                "reschedule_job: trigger raised for job_id=%s callable=%s trigger=%r",
                job.job_id,
                getattr(job.job, "__qualname__", str(job.job)),
                job.trigger,
            )
            await self._remove_job(job)
            return

        if next_run is None:
            await self._remove_job(job)
            return

        curr_next_run = job.next_run
        job.set_next_run(next_run)
        delta_to_now = (job.next_run - date_utils.now()).in_seconds()
        if delta_to_now <= 0:
            self.logger.warning(
                "Trigger produced non-future next_run (%.3fs in the past), advancing by 1s", -delta_to_now
            )
            job.set_next_run(date_utils.now().add(seconds=1))

        self.logger.debug(
            "Rescheduling repeating job %s from %s to %s",
            job,
            curr_next_run,
            job.next_run,
        )
        await self._enqueue_job(job)

    async def _test_trigger_due_jobs(self) -> int:
        """Fire all jobs due at the current time. For test harnesses only.

        Snapshots due jobs via a single ``pop_due_and_peek_next(date_utils.now())``
        call, then awaits each ``_dispatch_and_log(job)`` inline (not via
        ``task_bucket.spawn``). Jobs re-enqueued during dispatch (repeating jobs)
        are not included in this invocation — only the initial snapshot is
        processed, preventing infinite loops when the clock is frozen.

        This method bypasses the ``serve()`` loop's timing and wakeup logic.
        It is intended for use with ``AppTestHarness.trigger_due_jobs()`` and
        should not be called in production code.

        Returns:
            The number of jobs dispatched.
        """
        current_time = date_utils.now()
        due_jobs, _next_run = await self._job_queue.pop_due_and_peek_next(current_time)

        count = 0
        for job in due_jobs:
            await self._dispatch_and_log(job)
            count += 1

        return count

    async def get_all_jobs(self) -> list["ScheduledJob"]:
        """Return all currently scheduled jobs across all apps."""
        return await self._job_queue.get_all()

    def remove_jobs_by_owner(self, owner: str) -> asyncio.Task:
        """Remove all jobs for a given owner.

        Args:
            owner: The owner of the jobs to remove.
        """

        return self.task_bucket.spawn(self._remove_jobs_by_owner(owner), name="scheduler:remove_jobs_by_owner")

    def dequeue_job(self, job: "ScheduledJob") -> bool:
        """Remove a job from the scheduler synchronously, fire removal callbacks, and kick.

        Calls ``_ScheduledJobQueue.remove_item_sync`` directly (no lock). Fires
        ``_fire_removal_callbacks`` unconditionally — even when the job was not in
        the heap — to prevent dict leaks when the serve loop already popped the job.
        Calls ``kick()`` only when the job was actually removed from the heap.

        Args:
            job: The job to remove.

        Returns:
            True if the job was found and removed from the heap, False otherwise.
        """
        removed = self._job_queue.remove_item_sync(job)
        if removed:
            self.logger.debug("Dequeued job: %s", job)
            self.kick()
        else:
            self.logger.debug("Job not in heap (already popped by serve loop): %s", job)
        # Set _dequeued unconditionally — even when the job was already popped
        # from the heap by the serve loop. This prevents the dispatch race
        # (guard in _dispatch_and_log) and makes cancel idempotent.
        job._dequeued = True
        self._fire_removal_callbacks([job])
        return removed

    async def mark_job_cancelled(self, db_id: int) -> None:
        """Persist durable cancellation state for a job by setting ``cancelled_at`` in the DB.

        Delegates to ``CommandExecutor.mark_job_cancelled``. No-op when ``db_id`` is None.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as cancelled.
        """
        await self._executor.mark_job_cancelled(db_id)


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

    async def on_initialize(self) -> None:
        self.mark_ready(reason="Queue ready")

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.scheduler_service_log_level

    async def add(self, job: "ScheduledJob") -> None:
        """Add a job to the queue."""

        async with self._lock:
            self._queue.push(job)

        if job.fire_at != job.next_run:
            self.logger.debug(
                "Queued job %s for next_run=%s (fire_at=%s, jitter=%ss)",
                job,
                job.next_run,
                job.fire_at,
                job.jitter,
            )
        else:
            self.logger.debug("Queued job %s for %s", job, job.next_run)

    async def pop_due(self, reference_time: ZonedDateTime | None = None) -> list["ScheduledJob"]:
        """Return and remove all jobs due to run at or before the reference time."""

        due_jobs: list[ScheduledJob] = []

        async with self._lock:
            current_time = reference_time or date_utils.now()
            while not self._queue.is_empty():
                candidate = self._queue.peek()
                if candidate is None or candidate.fire_at > current_time:
                    break

                due_jobs.append(self._queue.pop())
                current_time = date_utils.now()

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
                if candidate is None or candidate.fire_at > current_time:
                    break

                due_jobs.append(self._queue.pop())
                current_time = date_utils.now()

            upcoming = self._queue.peek()
            next_run = upcoming.fire_at if upcoming else None

        if due_jobs:
            self.logger.debug("Dequeued %d due jobs", len(due_jobs))

        return due_jobs, next_run

    async def next_run_time(self) -> ZonedDateTime | None:
        """Return the next scheduled fire time (fire_at) if available."""

        async with self._lock:
            upcoming = self._queue.peek()
            return upcoming.fire_at if upcoming else None

    async def peek(self) -> "ScheduledJob | None":
        """Return the next scheduled job without removing it."""

        async with self._lock:
            return self._queue.peek()

    async def remove_owner(self, owner: str) -> "list[ScheduledJob]":
        """Remove all jobs belonging to the given owner. Returns the removed jobs."""

        async with self._lock:
            removed = self._queue.remove_where(lambda job: job.owner_id == owner)

        if removed:
            self.logger.debug("Removed %d jobs for owner '%s'", len(removed), owner)
        else:
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

    def remove_item_sync(self, job: "ScheduledJob") -> bool:
        """Remove a specific job from the heap synchronously, without acquiring the lock.

        Calls ``self._queue.remove_item(job)`` directly. Safe to call from
        synchronous code running on the event loop — other coroutines cannot
        interleave without an await point in asyncio's cooperative scheduler.

        Args:
            job: The job to remove.

        Returns:
            True if the job was found and removed, False otherwise.
        """
        return self._queue.remove_item(job)

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

        count = len(removed)
        if count:
            self.logger.debug("Cleared %d jobs from queue", count)

        return count


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

    def remove_where(self, predicate: Callable[[T], bool]) -> list[T]:
        """Remove all items matching the predicate, returning the removed items."""

        if not self._queue:
            return []

        remaining: list[T] = []
        removed: list[T] = []
        for item in self._queue:
            if predicate(item):
                removed.append(item)
            else:
                remaining.append(item)

        if removed:
            self._queue = remaining
            heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]

        return removed

    def remove_item(self, item: T) -> bool:
        """Remove a specific item from the queue if present."""

        if item not in self._queue:
            return False

        self._queue.remove(item)
        heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]
        return True
