"""Tests for TaskBucket.run_in_thread routing sync user code to the dedicated executor.

Covers:
- Sync user code submitted via run_in_thread runs on the dedicated pool
  (worker thread name carries the "hassette-sync" prefix).
- Framework asyncio.to_thread calls run on the default pool (no
  "hassette-sync" prefix).
- A slow sync handler under a short asyncio.timeout still surfaces
  TimeoutError to the caller — the timeout signal is unchanged.
- SyncWorkerHandle capture: handle.thread is set to the worker thread before _call returns.
"""

import asyncio
import threading
import time
from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

from hassette.task_bucket.task_bucket import SYNC_WORKER_HANDLE, TaskBucket
from hassette.test_utils import make_mock_hassette

# Shared fixture


@pytest.fixture
def hassette_mock() -> Iterator[AsyncMock]:
    """Hassette mock with a real sync executor (thread_name_prefix="hassette-sync").

    The executor is joined at teardown so its worker threads don't outlive the test.
    """
    hassette = make_mock_hassette()
    try:
        yield hassette
    finally:
        # Deterministically join the worker threads so they don't outlive the test.
        hassette.sync_executor.shutdown(join_threads_or_timeout=True)


@pytest.fixture
def bucket(hassette_mock) -> TaskBucket:
    """TaskBucket wired to the mock hassette."""
    return TaskBucket(hassette_mock)


# Sync user code runs on the dedicated pool


async def test_run_in_thread_uses_dedicated_executor(bucket: TaskBucket) -> None:
    """Worker thread name starts with 'hassette-sync' (the dedicated pool's prefix).

    Sync user code submitted through run_in_thread must land on the dedicated
    executor, not asyncio's default pool.
    """
    worker_name: list[str] = []

    def capture_thread_name() -> None:
        worker_name.append(threading.current_thread().name)

    await bucket.run_in_thread(capture_thread_name)

    assert worker_name, "worker thread name was not captured"
    assert worker_name[0].startswith("hassette-sync"), f"expected 'hassette-sync' prefix, got '{worker_name[0]}'"


async def test_run_in_thread_handle_captures_worker_thread(bucket: TaskBucket) -> None:
    """SYNC_WORKER_HANDLE holds the worker Thread after run_in_thread completes.

    The timeout site reads handle.thread.is_alive() — this test confirms the handle
    is populated via SYNC_WORKER_HANDLE and points at a Thread object (not still None).
    """

    def slow_fn() -> str:
        time.sleep(0.05)
        return "done"

    future = bucket.run_in_thread(slow_fn)
    handle = SYNC_WORKER_HANDLE.get()
    assert handle is not None, "SYNC_WORKER_HANDLE should be set after run_in_thread"

    # Before the future resolves, handle.thread may or may not be set yet (race) — but
    # after awaiting, it must be a Thread.
    result = await future
    assert result == "done"
    assert handle.thread is not None, "handle.thread should be a Thread after completion"
    assert isinstance(handle.thread, threading.Thread)


# Framework asyncio.to_thread still uses the default pool


async def test_asyncio_to_thread_uses_default_pool() -> None:
    """asyncio.to_thread runs on the loop-default pool, NOT the 'hassette-sync' pool.

    Framework-internal calls that use asyncio.to_thread directly are unaffected
    by the routing change in run_in_thread.
    """
    default_pool_thread_name: list[str] = []

    def capture() -> None:
        default_pool_thread_name.append(threading.current_thread().name)

    await asyncio.to_thread(capture)

    assert default_pool_thread_name, "thread name not captured"
    assert not default_pool_thread_name[0].startswith("hassette-sync"), (
        f"asyncio.to_thread landed on the dedicated pool: '{default_pool_thread_name[0]}'"
    )


async def test_pool_split_both_assertions_in_one_pass(bucket: TaskBucket) -> None:
    """Single test demonstrating the pool split: dedicated vs. default.

    Both assertions in one pass so the comparison is direct and not spread
    across separate test runs that could land on different machines with
    different pool configs.
    """
    dedicated_name: list[str] = []
    default_name: list[str] = []

    def capture_dedicated() -> None:
        dedicated_name.append(threading.current_thread().name)

    def capture_default() -> None:
        default_name.append(threading.current_thread().name)

    # Run both submissions concurrently and wait for both
    await asyncio.gather(
        bucket.run_in_thread(capture_dedicated),
        asyncio.to_thread(capture_default),
    )

    assert dedicated_name[0].startswith("hassette-sync"), (
        f"run_in_thread worker should be on dedicated pool, got '{dedicated_name[0]}'"
    )
    assert not default_name[0].startswith("hassette-sync"), (
        f"asyncio.to_thread worker should NOT be on dedicated pool, got '{default_name[0]}'"
    )


# Timeout signal unchanged


async def test_slow_sync_handler_timeout_signal_unchanged(bucket: TaskBucket) -> None:
    """A slow sync handler under asyncio.timeout still raises TimeoutError to the caller.

    The caller-visible timeout contract is preserved after the routing change.
    The handler sleeps longer than the timeout; the await must unblock with TimeoutError.
    """
    handler_ran_to_completion = threading.Event()

    def slow_handler() -> None:
        # Sleep past the timeout — the worker keeps running after the caller unblocks
        # (the known thread-leak behaviour, not a bug). Kept short (0.5s) and joined
        # below so the leaked worker does not outlive the test in the session-scoped loop.
        time.sleep(0.5)
        handler_ran_to_completion.set()

    adapted = bucket.make_async_adapter(slow_handler)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            await adapted()

    # Bound the leak: wait for the worker to finish before the test returns so it
    # cannot bleed into later tests sharing the session executor.
    assert handler_ran_to_completion.wait(timeout=2.0)


async def test_timeout_error_propagates_through_make_async_adapter(bucket: TaskBucket) -> None:
    """TimeoutError raised inside the sync fn propagates cleanly (no swallow by except Exception).

    Regression guard for the re-raise path in make_async_adapter._sync_fn.
    """

    def raise_timeout() -> None:
        raise TimeoutError("explicit timeout from handler")

    adapted = bucket.make_async_adapter(raise_timeout)

    with pytest.raises(TimeoutError, match="explicit timeout from handler"):
        await adapted()
