"""Integration tests for thread-leaked observability.

Verifies that a sync handler whose worker thread outlives the asyncio timeout
produces an execution record with ``thread_leaked=True``, and that a "not-started"
timeout (worker never dequeued) does not misfire.

All tests exercise the real dedicated executor (InterruptibleThreadPoolExecutor)
via ``make_mock_hassette()``, not a mock pool.
"""

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock

import pytest

from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.sync_executor import SyncExecutor
from hassette.task_bucket.task_bucket import TaskBucket
from tests.support.factories import make_listener_registration, make_mock_listener
from tests.support.mock_hassette import make_mock_hassette

from .conftest import invoke_cmd, pop_execution_record

InvokeFn = Callable[[object], Awaitable[None]]


def sync_invoker(sync_executor: SyncExecutor, handler: Callable[[object], None]) -> InvokeFn:
    """Wrap a sync handler in the async adapter the bus uses, so it runs on a pool worker."""
    adapted = TaskBucket(make_mock_hassette(), sync_executor=sync_executor).make_async_adapter(handler)

    async def invoke(event: object) -> None:
        await adapted(event)

    return invoke


def make_invoker_listener(invoke: InvokeFn) -> MagicMock:
    """Listener that dispatches to `invoke`, carrying the identity fields the executor reads."""
    listener = make_mock_listener()
    listener.invoker.invoke = invoke
    listener.invoker.error_handler = None
    listener.identity.app_key = "test_app"
    listener.identity.instance_index = 0
    return listener


def assert_timed_out(executor: CommandExecutor, *, thread_leaked: bool, reason: str) -> None:
    """Assert the queued record is a timeout with the expected thread_leaked verdict."""
    record = pop_execution_record(executor)
    assert record.status == "timed_out"
    assert record.thread_leaked is thread_leaked, reason


# Not-started sync timeout → thread_leaked=False (handle.thread still None)


async def test_not_started_sync_timeout_no_false_positive(
    executor: CommandExecutor,
    sync_executor: SyncExecutor,
) -> None:
    """run_in_thread is called but worker hasn't dequeued before timeout → thread_leaked=False.

    Saturates the pool (max_workers=2) with two long-running blockers so that the
    third submission sits in the queue.  When the asyncio timeout fires, handle.thread is
    still None (the worker never called _call), so the liveness guard must not flag
    thread_leaked.  Exercises the ``handle.thread is not None`` branch in _execute.
    """
    pool_gate = threading.Event()
    started = threading.Barrier(3)

    def pool_filler() -> None:
        started.wait(timeout=2.0)
        pool_gate.wait(timeout=10.0)

    # Submit two jobs to saturate both workers (max_workers=2 on the sync executor's pool).
    # Use the underlying executor directly so these don't touch SYNC_WORKER_HANDLE.
    loop = asyncio.get_running_loop()
    filler_f1 = loop.run_in_executor(sync_executor.executor, pool_filler)
    filler_f2 = loop.run_in_executor(sync_executor.executor, pool_filler)

    # Wait until both fillers have definitely dequeued and started.
    await asyncio.to_thread(started.wait, 2.0)

    # Now submit the real handler — it will queue behind the two fillers.
    def sync_fn(_event: object) -> None:
        pass  # never reached within the test

    listener = make_invoker_listener(sync_invoker(sync_executor, sync_fn))

    # 10ms timeout — fires before the pool has a free slot
    await executor.execute(invoke_cmd(listener, listener_id=4, effective_timeout=0.01))

    # Release the pool fillers so they exit before teardown.
    pool_gate.set()
    await asyncio.gather(filler_f1, filler_f2, return_exceptions=True)

    assert_timed_out(
        executor,
        thread_leaked=False,
        reason="thread_leaked must be False when worker never dequeued (handle.thread is None)",
    )


# Blocked sync handler past timeout → thread_leaked=True


async def test_sync_handler_timeout_sets_thread_leaked(
    executor: CommandExecutor,
    sync_executor: SyncExecutor,
) -> None:
    """A sync handler blocking past its timeout produces thread_leaked=True.

    The handler sleeps for much longer than the timeout; when asyncio cancels
    the await the worker thread is still alive, so the liveness check fires.
    """
    released = threading.Event()

    def sync_blocking(_event: object) -> None:
        # Block until released (or 5s safety cap) so the worker is definitely
        # alive when the asyncio timeout fires.
        released.wait(timeout=5.0)

    listener = make_invoker_listener(sync_invoker(sync_executor, sync_blocking))

    # 50ms timeout — the worker will still be alive when it fires
    await executor.execute(invoke_cmd(listener, effective_timeout=0.05))

    # Release the worker so it can exit cleanly after the test.
    released.set()

    assert_timed_out(
        executor,
        thread_leaked=True,
        reason="Expected thread_leaked=True for a sync handler still alive after timeout",
    )


# Async handler timeout → thread_leaked=False (no worker thread involved)


async def test_async_handler_timeout_does_not_set_thread_leaked(
    executor: CommandExecutor,
) -> None:
    """An async handler that times out does NOT set thread_leaked (no worker thread)."""

    async def slow_async(_event: object) -> None:
        await asyncio.sleep(10.0)

    listener = make_invoker_listener(slow_async)

    await executor.execute(invoke_cmd(listener, listener_id=2, effective_timeout=0.05))

    assert_timed_out(
        executor,
        thread_leaked=False,
        reason="thread_leaked must be False for async handlers (no worker thread)",
    )


# Thread-leaked distinguishable from clean timeout (thread finishes before check)


async def test_pure_async_timeout_no_handle_no_thread_leaked(
    executor: CommandExecutor,
) -> None:
    """A pure async handler that times out (no run_in_thread) sets thread_leaked=False.

    SYNC_WORKER_HANDLE is never set because no run_in_thread call occurs, so the
    liveness guard sees handle=None and does not flag the execution.  This is the
    primary "not-started" / "no worker" gate.
    """

    async def async_slow(_event: object) -> None:
        await asyncio.sleep(10.0)

    listener = make_invoker_listener(async_slow)

    await executor.execute(invoke_cmd(listener, listener_id=3, effective_timeout=0.05))

    assert_timed_out(
        executor,
        thread_leaked=False,
        reason="No worker thread — handle is None, so thread_leaked must be False",
    )


# Completed sync handler with user-code TimeoutError → thread_leaked=False
# (regression test for handle.active guard)


async def test_completed_sync_handler_no_false_thread_leaked(
    executor: CommandExecutor,
    sync_executor: SyncExecutor,
) -> None:
    """A sync handler that raises TimeoutError from user code must not set thread_leaked.

    When a sync handler raises TimeoutError itself (not from the framework timeout),
    result.is_timed_out is True and the pool thread is still alive (pool threads persist
    between jobs).  Without the handle.active guard, handle.thread.is_alive() alone
    would cause a false thread_leaked=True.  The active flag — cleared by _call's finally
    block when the handler returns/raises — prevents this false positive.
    """

    def sync_raises_timeout(_event: object) -> None:
        raise TimeoutError("user-code timeout")

    listener = make_invoker_listener(sync_invoker(sync_executor, sync_raises_timeout))

    # No framework timeout — the TimeoutError comes from user code
    await executor.execute(invoke_cmd(listener, listener_id=5))

    assert_timed_out(
        executor,
        thread_leaked=False,
        reason=(
            "thread_leaked must be False when the sync handler completed (active=False) "
            "even though the pool thread is still alive"
        ),
    )


# Round-trip persistence — thread_leaked column survives write+read back


@pytest.mark.parametrize("thread_leaked", [True, False], ids=["leaked", "not_leaked"])
async def test_thread_leaked_round_trips_through_db(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    thread_leaked: bool,
) -> None:
    """The thread_leaked flag persists to the DB and reads back as 1/0.

    Verifies the 004.sql migration column is wired end-to-end: execution_insert_params →
    INSERT → SELECT. The record is built directly rather than via build_record, because
    build_record with a MagicMock event would try to bind a MagicMock origin to SQLite.
    """
    db_service, session_id = initialized_db

    # Register the listener so the FK constraint is satisfied.
    listener_id = await executor.register_listener(make_listener_registration(topic="test"))

    execution_id = f"test-exec-thread-leaked-{thread_leaked}"
    record = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=55.0,
        status="timed_out",
        thread_leaked=thread_leaked,
        error_type="TimeoutError",
        error_message="execution timed out",
        execution_id=execution_id,
    )

    await executor.persist_batch([record])

    cursor = await db_service.db.execute(
        "SELECT thread_leaked FROM executions WHERE execution_id = ?",
        (execution_id,),
    )
    row = await cursor.fetchone()
    assert row is not None, "execution row not found after persist"
    assert row[0] == int(thread_leaked)
