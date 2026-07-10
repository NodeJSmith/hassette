"""Unit tests for TaskBucket.

Tests cover the snapshot-semantics and filtering guarantees of
``TaskBucket.pending_tasks()``:

- Returns an empty list for a fresh bucket with no tasks
- Returns only non-completed tasks that are currently running
- Excludes tasks that have already completed
- Excludes tasks that have been cancelled
- Returns a new list (snapshot) each call — not a reference to the internal set

Cross-thread spawn:
- Raises RuntimeError (not hangs) when the event loop is stopped
"""

import asyncio
import threading
from concurrent.futures import Future as CfFuture
from concurrent.futures import TimeoutError as CfTimeout
from unittest.mock import patch

import pytest

from hassette.task_bucket import TaskBucket
from hassette.test_utils import make_mock_hassette


@pytest.fixture
def hassette_mock():
    """Minimal Hassette mock sufficient to construct a TaskBucket."""
    return make_mock_hassette()


@pytest.fixture
def bucket(hassette_mock) -> TaskBucket:
    """Fresh TaskBucket with no tasks tracked."""
    return TaskBucket(hassette_mock)


async def test_pending_tasks_returns_empty_for_fresh_bucket(bucket: TaskBucket) -> None:
    """A newly-created TaskBucket with no tasks returns an empty list."""
    assert bucket.pending_tasks() == []


async def test_pending_tasks_returns_active_tasks(bucket: TaskBucket) -> None:
    """Tasks that are currently running appear in pending_tasks()."""
    gate = asyncio.Event()

    async def _sleeper() -> None:
        await gate.wait()

    t1 = asyncio.create_task(_sleeper())
    t2 = asyncio.create_task(_sleeper())
    bucket._tasks.add(t1)
    bucket._tasks.add(t2)

    # Yield control so the tasks start executing and block on gate
    await asyncio.sleep(0)

    pending = bucket.pending_tasks()
    assert len(pending) == 2
    assert t1 in pending
    assert t2 in pending

    # Clean up
    gate.set()
    await asyncio.gather(t1, t2, return_exceptions=True)


async def test_pending_tasks_excludes_completed_tasks(bucket: TaskBucket) -> None:
    """Tasks that have completed are not included in pending_tasks()."""

    async def _done() -> None:
        await asyncio.sleep(0)

    t = asyncio.create_task(_done())
    bucket._tasks.add(t)

    # Let the task complete
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert t.done()
    assert t not in bucket.pending_tasks()


async def test_pending_tasks_excludes_cancelled_tasks(bucket: TaskBucket) -> None:
    """Tasks that have been cancelled are not included in pending_tasks()."""

    async def _long_sleep() -> None:
        await asyncio.sleep(100)

    t = asyncio.create_task(_long_sleep())
    bucket._tasks.add(t)

    # Cancel and wait for cancellation to propagate
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t

    assert t.cancelled()
    assert t not in bucket.pending_tasks()


async def test_pending_tasks_returns_snapshot_not_reference(bucket: TaskBucket) -> None:
    """pending_tasks() returns a new list each call, not the internal set.

    This is the snapshot-semantics guarantee: mutating the returned list or
    completing tasks between calls must not affect a previously-returned result.
    """
    gate = asyncio.Event()

    async def _sleeper() -> None:
        await gate.wait()

    t = asyncio.create_task(_sleeper())
    bucket._tasks.add(t)
    await asyncio.sleep(0)

    snapshot = bucket.pending_tasks()
    assert t in snapshot

    # Mark the task as done via cancellation
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t

    # The old snapshot is unchanged
    assert t in snapshot

    # But a fresh call reflects the updated state
    assert t not in bucket.pending_tasks()


class TestSpawnTaskNaming:
    """spawn() should derive a meaningful task name from the coroutine when none is given."""

    @pytest.fixture
    async def spawn_bucket(self, bucket: TaskBucket) -> TaskBucket:
        # _loop_thread_id and loop are already set by make_mock_hassette()
        return bucket

    async def test_spawn_without_name_uses_coroutine_qualname(self, spawn_bucket: TaskBucket) -> None:
        gate = asyncio.Event()

        async def my_important_task() -> None:
            await gate.wait()

        task = spawn_bucket.spawn(my_important_task())
        assert "my_important_task" in task.get_name()

        gate.set()
        await task

    async def test_spawn_with_explicit_name_preserves_it(self, spawn_bucket: TaskBucket) -> None:
        gate = asyncio.Event()

        async def some_coro() -> None:
            await gate.wait()

        task = spawn_bucket.spawn(some_coro(), name="my-custom-name")
        assert task.get_name() == "my-custom-name"

        gate.set()
        await task


class TestCrossThreadSpawnTimeout:
    """Cross-thread spawn raises RuntimeError instead of hanging when the loop is unresponsive."""

    async def test_cross_thread_spawn_timeout_raises_runtime_error(self) -> None:
        """spawn() wraps CfTimeoutError into a descriptive RuntimeError."""
        mock_h = make_mock_hassette()
        mock_h.loop_thread_id = -1  # force cross-thread path
        bucket = TaskBucket(mock_h)

        error: Exception | None = None

        async def noop() -> None:
            pass

        def try_spawn() -> None:
            nonlocal error
            try:
                bucket.spawn(noop(), name="doomed-task")
            except RuntimeError as exc:
                error = exc

        with patch.object(CfFuture, "result", side_effect=CfTimeout("timed out")):
            t = threading.Thread(target=try_spawn)
            t.start()
            t.join(timeout=5.0)

        assert not t.is_alive(), "Spawn thread should not hang"
        assert error is not None, "Expected RuntimeError from timed-out cross-thread spawn"
        assert "doomed-task" in str(error)
        assert "timed out" in str(error).lower()
