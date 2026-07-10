"""Unit tests for SchedulerService.dequeue_job and _ScheduledJobQueue.remove_item_sync.

Tests verify:
- dequeue_job removes job from heap synchronously
- dequeue_job returns False when job not in heap (idempotent no-op)
- dequeue_job fires removal callbacks when removed
- dequeue_job fires removal callbacks even when job was NOT in heap
- dequeue_job calls kick() only when job was removed
- dequeue_job is synchronous (no yield point)
"""

import inspect
from unittest.mock import MagicMock

from fair_async_rlock import FairAsyncRLock

from hassette.core.scheduler_service import HeapQueue, SchedulerService, _ScheduledJobQueue
from hassette.test_utils.factories import make_scheduled_job

from .conftest import make_scheduler_service


def make_dequeue_service() -> SchedulerService:
    """SchedulerService with a real _ScheduledJobQueue for heap-operation tests."""
    svc = make_scheduler_service()

    # Override the mock job queue with a real one so we can test actual heap state
    queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
    queue._lock = FairAsyncRLock()
    queue._queue = HeapQueue()
    queue.logger = MagicMock()
    svc._job_queue = queue

    return svc


class TestRemoveItemSync:
    async def test_remove_item_sync_removes_job_from_heap(self) -> None:
        """remove_item_sync returns True and job is absent from heap afterward."""
        queue = _ScheduledJobQueue.__new__(_ScheduledJobQueue)
        queue._lock = FairAsyncRLock()
        queue._queue = HeapQueue()
        queue.logger = MagicMock()

        job = make_scheduled_job()
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

        job = make_scheduled_job()
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


class TestDequeueJobRemovesFromHeap:
    async def test_dequeue_job_removes_from_heap(self) -> None:
        """dequeue_job removes the job from the queue."""
        svc = make_dequeue_service()
        job = make_scheduled_job()
        svc._job_queue._queue.push(job)

        removed = svc.dequeue_job(job)

        assert removed is True
        assert job not in list(svc._job_queue._queue)

    async def test_dequeue_job_returns_false_when_not_in_heap(self) -> None:
        """dequeue_job returns False when job is not in the heap (idempotent no-op)."""
        svc = make_dequeue_service()
        job = make_scheduled_job()
        # Do NOT push job

        removed = svc.dequeue_job(job)

        assert removed is False


class TestDequeueJobRemovalCallbacks:
    async def test_dequeue_job_fires_removal_callbacks_when_removed(self) -> None:
        """dequeue_job fires removal callback when job was in the heap."""
        svc = make_dequeue_service()
        job = make_scheduled_job(owner_id="owner_a")
        svc._job_queue._queue.push(job)

        callback = MagicMock()
        svc.register_removal_callback("owner_a", callback)

        svc.dequeue_job(job)

        callback.assert_called_once_with(job)

    async def test_dequeue_job_fires_removal_callbacks_when_not_removed(self) -> None:
        """dequeue_job fires removal callback even when job was NOT in the heap.

        This prevents dict leaks when the serve loop already popped the job.
        """
        svc = make_dequeue_service()
        job = make_scheduled_job(owner_id="owner_b")
        # Do NOT push — simulate job already popped by serve loop

        callback = MagicMock()
        svc.register_removal_callback("owner_b", callback)

        svc.dequeue_job(job)

        callback.assert_called_once_with(job)


class TestDequeueJobKick:
    async def test_dequeue_job_calls_kick_only_when_removed(self) -> None:
        """kick() is called only when the job was in the heap and removed."""
        svc = make_dequeue_service()
        kick_calls = []

        def _spy_kick():
            kick_calls.append(1)

        svc.kick = _spy_kick  # pyright: ignore[reportAttributeAccessIssue]

        # Case 1: job IS in the heap → kick should be called
        job1 = make_scheduled_job()
        svc._job_queue._queue.push(job1)
        svc.dequeue_job(job1)
        assert len(kick_calls) == 1, "kick() should be called when job was removed"

        # Case 2: job NOT in the heap → kick should NOT be called again
        kick_calls.clear()
        job2 = make_scheduled_job()
        svc.dequeue_job(job2)
        assert len(kick_calls) == 0, "kick() must NOT be called when job was not in heap"


class TestDequeueJobIsSynchronous:
    def test_dequeue_job_is_synchronous(self) -> None:
        """dequeue_job must be a synchronous method — no yield points."""
        svc = SchedulerService.__new__(SchedulerService)
        assert not inspect.iscoroutinefunction(svc.dequeue_job), "dequeue_job must be synchronous — no async def"


class TestDispatchRaceGuard:
    """Regression test for the dispatch race window (#518 spec).

    Scenario: serve loop pops a job into due_jobs, then cancel_job runs
    before dispatch_and_log executes. The _dequeued guard must prevent
    the handler from firing. dispatch_and_log now routes through
    run_job_with_guard (the guard-aware entry point) rather than directly
    to run_job, so the spy in test_dispatch_runs_non_dequeued_job targets
    run_job_with_guard.
    """

    async def test_dispatch_skips_dequeued_job(self) -> None:
        """dispatch_and_log returns immediately when job._dequeued is True."""
        svc = make_dequeue_service()
        job = make_scheduled_job()

        # Simulate the race: job was popped from heap, then cancelled
        job._dequeued = True

        # Spy run_job_with_guard — the entry point dispatch_and_log actually routes
        # through. Spying run_job here would be vacuous: the guard path is never run_job,
        # so a broken _dequeued guard would still leave run_called False and pass.
        run_called = False

        async def spy_run_job_with_guard(_j):
            nonlocal run_called
            run_called = True

        svc.run_job_with_guard = spy_run_job_with_guard  # pyright: ignore[reportAttributeAccessIssue]

        await svc.dispatch_and_log(job)
        assert not run_called, "run_job_with_guard must NOT be called when job._dequeued is True"

    async def test_dispatch_runs_non_dequeued_job(self) -> None:
        """dispatch_and_log proceeds normally when job._dequeued is False."""
        svc = make_dequeue_service()
        job = make_scheduled_job()
        job._dequeued = False

        run_called = False

        async def spy_run_job_with_guard(_j):
            nonlocal run_called
            run_called = True

        svc.run_job_with_guard = spy_run_job_with_guard  # pyright: ignore[reportAttributeAccessIssue]

        await svc.dispatch_and_log(job)
        assert run_called, "run_job_with_guard must be called when job._dequeued is False"
