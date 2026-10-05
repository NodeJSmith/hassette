import heapq
import typing
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from fair_async_rlock import FairAsyncRLock
from hassette_wire import LogLevel, ScheduleStatus
from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.resources.base import Resource
from hassette.resources.lifecycle import mark_ready

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.scheduler.classes import Job

__all__ = ["HeapQueue", "_ScheduledJobQueue"]

T = TypeVar("T")


class _ScheduledJobQueue(Resource):
    """Encapsulates the scheduler heap with fair locking semantics."""

    _lock: FairAsyncRLock
    """Lock to protect access to the queue."""

    _queue: "HeapQueue[Job]"
    """The heap queue of scheduled jobs."""

    def __init__(self, hassette: "Hassette", *, parent: Resource | None = None) -> None:
        super().__init__(hassette, parent=parent)
        self._lock = FairAsyncRLock()
        self._queue = HeapQueue()

    async def on_initialize(self) -> None:
        mark_ready(self, reason="Queue ready")

    @property
    def config_log_level(self) -> LogLevel:
        return self.hassette.config.logging.scheduler_service

    async def add(self, job: "Job") -> None:
        """Add a job to the queue.

        The due-time heap must contain only jobs with a concrete automatic occurrence —
        rejects any job that is not ``SCHEDULED`` or lacks a concrete ``next_run`` before
        ever touching the heap, so a waiting/completed/manual job can never corrupt heap
        comparisons with a missing timestamp.

        The ``_dequeued`` flag is re-checked inside the lock, atomic with the heap
        push, to guard against a cancel arriving at any await point after the entry-level
        check in ``dispatch_and_log`` and before the push here. ``dequeue_job``
        sets ``_dequeued`` lock-free but on the same event-loop thread, so the in-lock
        read here sees any set that preceded this lock acquisition.

        Raises:
            ValueError: If ``job.schedule_status`` is not ``SCHEDULED``, or ``job.next_run``
                is ``None``.
        """
        if job.schedule_status is not ScheduleStatus.SCHEDULED or job.next_run is None:
            raise ValueError(
                f"Cannot enqueue job {job.name!r}: only SCHEDULED jobs with a concrete "
                f"next_run may enter the heap (schedule_status={job.schedule_status!r}, "
                f"next_run={job.next_run!r})"
            )

        async with self._lock:
            if job._dequeued:
                self.logger.debug("Job %s was dequeued during re-enqueue window; skipping push", job)
                return
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

    async def pop_due_and_peek_next(self, reference_time: ZonedDateTime) -> tuple[list["Job"], ZonedDateTime | None]:
        """Pop all due jobs and return the next run time in a single lock acquisition."""
        due_jobs: list[Job] = []

        async with self._lock:
            current_time = reference_time
            while not self._queue.is_empty():
                candidate = self._queue.peek()
                if candidate is None:
                    break
                # Heap invariant, enforced by add(): every enqueued job has a concrete fire_at.
                assert candidate.fire_at is not None
                if candidate.fire_at > current_time:
                    break

                due_jobs.append(self._queue.pop())
                current_time = date_utils.now()

            upcoming = self._queue.peek()
            next_run = upcoming.fire_at if upcoming else None

        if due_jobs:
            self.logger.debug("Dequeued %d due jobs", len(due_jobs))

        return due_jobs, next_run

    async def remove_job(self, job: "Job") -> bool:
        """Remove a specific job if it exists.

        Not to be confused with ``SchedulerService.remove_job``, which performs the full
        registry+heap+guard+persistence removal operation.
        """
        async with self._lock:
            removed = self._queue.remove_item(job)

        if removed:
            self.logger.debug("Removed job: %s", job)
            return removed

        self.logger.debug("Job not found in queue, cannot remove: %s", job)
        return removed

    def remove_item_sync(self, job: "Job") -> bool:
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

    async def get_all(self) -> list["Job"]:
        """Return a snapshot of all queued jobs (non-destructive)."""
        async with self._lock:
            return list(self._queue)


@dataclass
class HeapQueue(Generic[T]):
    _queue: list[T] = field(default_factory=list)

    def __iter__(self) -> Iterator[T]:
        """Iterate over all items in the queue (unordered)."""
        return iter(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

    def push(self, job: T) -> None:
        """Push a job onto the queue."""
        heapq.heappush(self._queue, job)  # pyright: ignore[reportArgumentType]

    def pop(self) -> T:
        """Pop the next job from the queue."""
        return heapq.heappop(self._queue)  # pyright: ignore[reportArgumentType]

    def peek(self) -> T | None:
        """Peek at the next job without removing it.

        Returns:
            T | None: The next job in the queue, or None if the queue is empty
        """
        return self._queue[0] if self._queue else None

    def is_empty(self) -> bool:
        """Check if the queue is empty."""
        return not self._queue

    def remove_item(self, item: T) -> bool:
        """Remove a specific item from the queue if present, by identity.

        Identity-based (not ``in``/``__eq__``, which compares ``sort_index`` on ``Job``):
        a job that was never enqueued (waiting, completed, or manual-only — never assigned
        a ``sort_index``, an ``init=False`` field with no default) can reach this method via
        ``dequeue_job()``/``Job.remove()`` regardless of whether it ever touched the heap. An
        ``__eq__``-based lookup would raise ``AttributeError`` reading the missing field;
        identity comparison never touches it.
        """
        for index, candidate in enumerate(self._queue):
            if candidate is item:
                del self._queue[index]
                heapq.heapify(self._queue)  # pyright: ignore[reportArgumentType]
                return True
        return False
