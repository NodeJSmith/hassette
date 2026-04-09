"""Unit tests for TaskBucket.pending_tasks() public accessor.

Tests cover the snapshot-semantics and filtering guarantees of
``TaskBucket.pending_tasks()``:

- Returns an empty list for a fresh bucket with no tasks
- Returns only non-completed tasks that are currently running
- Excludes tasks that have already completed
- Excludes tasks that have been cancelled
- Returns a new list (snapshot) each call — not a reference to the internal WeakSet
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from hassette.task_bucket import TaskBucket

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hassette_mock() -> MagicMock:
    """Return a MagicMock Hassette with just enough attributes for TaskBucket.__init__."""
    hassette = MagicMock()
    hassette.config.task_bucket_log_level = "DEBUG"
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.log_level = "DEBUG"
    return hassette


@pytest.fixture
def hassette_mock() -> MagicMock:
    """Minimal Hassette mock sufficient to construct a TaskBucket."""
    return _make_hassette_mock()


@pytest.fixture
def bucket(hassette_mock: MagicMock) -> TaskBucket:
    """Fresh TaskBucket with no tasks tracked."""
    return TaskBucket(hassette_mock)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


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
    """pending_tasks() returns a new list each call, not the internal WeakSet.

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
