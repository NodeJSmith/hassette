import typing
from collections.abc import Callable
from typing import Any

from fair_async_rlock import FairAsyncRLock
from whenever import SystemDateTime

from hassette.core.classes.resource import Resource

from .classes import HeapQueue, ScheduledJob
from .triggers import now

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette


class _ScheduledJobQueue(Resource):  # pyright: ignore[reportUnusedClass]
    """Encapsulates the scheduler heap with fair locking semantics."""

    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)
        self.set_logger_to_level(self.hassette.config.scheduler_service_log_level)

        self._lock = FairAsyncRLock()
        self._queue: HeapQueue[ScheduledJob] = HeapQueue()

        self.mark_ready(reason="Queue ready")

    async def add(self, job: ScheduledJob) -> None:
        """Add a job to the queue."""

        async with self._lock:
            self._queue.push(job)

        self.logger.debug("Queued job %s for %s", job, job.next_run)

    async def pop_due(self, reference_time: SystemDateTime | None = None) -> list[ScheduledJob]:
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

    async def peek(self) -> ScheduledJob | None:
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

    async def remove_job(self, job: ScheduledJob) -> bool:
        """Remove a specific job if it exists."""

        async with self._lock:
            removed = self._queue.remove_item(job)

        if removed:
            self.logger.debug("Removed job: %s", job)
        else:
            self.logger.debug("Job not found in queue, cannot remove: %s", job)

        return removed

    async def clear(self, predicate: Callable[[ScheduledJob], bool] | None = None) -> int:
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
