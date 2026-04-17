"""Unit tests for SchedulerService.dequeue_job and _ScheduledJobQueue.remove_item_sync (WP01).

Tests verify:
- dequeue_job removes job from heap synchronously
- dequeue_job returns False when job not in heap (idempotent no-op)
- dequeue_job fires removal callbacks when removed
- dequeue_job fires removal callbacks even when job was NOT in heap
- dequeue_job calls kick() only when job was removed
- dequeue_job is synchronous (no yield point)
"""

import asyncio
import inspect
from collections import defaultdict
from unittest.mock import MagicMock

from fair_async_rlock import FairAsyncRLock

import hassette.utils.date_utils as date_utils
from hassette.core.scheduler_service import HeapQueue, SchedulerService, _ScheduledJobQueue
from hassette.scheduler.classes import ScheduledJob

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(owner_id: str = "test_owner") -> ScheduledJob:
    """Create a minimal ScheduledJob for testing."""
    now = date_utils.now()
    return ScheduledJob(
        owner_id=owner_id,
        next_run=now,
        job=lambda: None,
    )


def _make_scheduler_service() -> SchedulerService:
    """Create a SchedulerService with a real _ScheduledJobQueue."""
    svc = SchedulerService.__new__(SchedulerService)
    svc.hassette = MagicMock()
    svc.hassette.config.registration_await_timeout = 30
    svc.hassette.config.scheduler_behind_schedule_threshold_seconds = 60
    svc._pending_registration_tasks = defaultdict(list)
    svc._removal_callbacks = {}
    svc.logger = MagicMock()
    svc._wakeup_event = asyncio.Event()

    # Real job queue so we can test actual heap state
    queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
    queue._lock = FairAsyncRLock()
    queue._queue = HeapQueue()
    queue.logger = MagicMock()
    svc._job_queue = queue

    return svc


# ---------------------------------------------------------------------------
# _ScheduledJobQueue.remove_item_sync
# ---------------------------------------------------------------------------


class TestRemoveItemSync:
    async def test_remove_item_sync_removes_job_from_heap(self) -> None:
        """remove_item_sync returns True and job is absent from heap afterward."""
        queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
        queue._lock = FairAsyncRLock()
        queue._queue = HeapQueue()
        queue.logger = MagicMock()

        job = _make_job()
        queue._queue.push(job)

        result = queue.remove_item_sync(job)

        assert result is True
        assert job not in list(queue._queue)

    async def test_remove_item_sync_returns_false_when_not_present(self) -> None:
        """remove_item_sync returns False when job is not in the heap."""
        queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
        queue._lock = FairAsyncRLock()
        queue._queue = HeapQueue()
        queue.logger = MagicMock()

        job = _make_job()
        # Do NOT push — job is not in the queue

        result = queue.remove_item_sync(job)

        assert result is False

    def test_remove_item_sync_does_not_acquire_lock(self) -> None:
        """remove_item_sync is synchronous — it must not acquire the FairAsyncRLock."""
        queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
        queue._lock = FairAsyncRLock()
        queue._queue = HeapQueue()
        queue.logger = MagicMock()

        # Verify the method is synchronous (not a coroutine function)
        assert not inspect.iscoroutinefunction(queue.remove_item_sync), (
            "remove_item_sync must be synchronous — it must not be async"
        )

        # Verify the source does not contain 'async with self._lock'
        src = inspect.getsource(queue.remove_item_sync)
        assert "async with" not in src, "remove_item_sync must not use async with"


# ---------------------------------------------------------------------------
# SchedulerService.dequeue_job
# ---------------------------------------------------------------------------


class TestDequeueJobRemovesFromHeap:
    async def test_dequeue_job_removes_from_heap(self) -> None:
        """dequeue_job removes the job from the queue."""
        svc = _make_scheduler_service()
        job = _make_job()
        svc._job_queue._queue.push(job)

        removed = svc.dequeue_job(job)

        assert removed is True
        assert job not in list(svc._job_queue._queue)

    async def test_dequeue_job_returns_false_when_not_in_heap(self) -> None:
        """dequeue_job returns False when job is not in the heap (idempotent no-op)."""
        svc = _make_scheduler_service()
        job = _make_job()
        # Do NOT push job

        removed = svc.dequeue_job(job)

        assert removed is False


class TestDequeueJobRemovalCallbacks:
    async def test_dequeue_job_fires_removal_callbacks_when_removed(self) -> None:
        """dequeue_job fires removal callback when job was in the heap."""
        svc = _make_scheduler_service()
        job = _make_job(owner_id="owner_a")
        svc._job_queue._queue.push(job)

        callback = MagicMock()
        svc.register_removal_callback("owner_a", callback)

        svc.dequeue_job(job)

        callback.assert_called_once_with(job)

    async def test_dequeue_job_fires_removal_callbacks_when_not_removed(self) -> None:
        """dequeue_job fires removal callback even when job was NOT in the heap.

        This prevents dict leaks when the serve loop already popped the job.
        """
        svc = _make_scheduler_service()
        job = _make_job(owner_id="owner_b")
        # Do NOT push — simulate job already popped by serve loop

        callback = MagicMock()
        svc.register_removal_callback("owner_b", callback)

        svc.dequeue_job(job)

        callback.assert_called_once_with(job)


class TestDequeueJobKick:
    async def test_dequeue_job_calls_kick_only_when_removed(self) -> None:
        """kick() is called only when the job was in the heap and removed."""
        svc = _make_scheduler_service()
        kick_calls = []

        def _spy_kick():
            kick_calls.append(1)

        svc.kick = _spy_kick  # pyright: ignore[reportAttributeAccessIssue]

        # Case 1: job IS in the heap → kick should be called
        job1 = _make_job()
        svc._job_queue._queue.push(job1)
        svc.dequeue_job(job1)
        assert len(kick_calls) == 1, "kick() should be called when job was removed"

        # Case 2: job NOT in the heap → kick should NOT be called again
        kick_calls.clear()
        job2 = _make_job()
        svc.dequeue_job(job2)
        assert len(kick_calls) == 0, "kick() must NOT be called when job was not in heap"


class TestDequeueJobIsSynchronous:
    def test_dequeue_job_is_synchronous(self) -> None:
        """dequeue_job must be a synchronous method — no yield points."""
        svc = SchedulerService.__new__(SchedulerService)
        assert not inspect.iscoroutinefunction(svc.dequeue_job), "dequeue_job must be synchronous — no async def"
