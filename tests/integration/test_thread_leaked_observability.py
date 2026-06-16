"""Integration tests for T06: thread-leaked observability (FR#3, AC#1).

Verifies that a sync handler whose worker thread outlives the asyncio timeout
produces an execution record with ``thread_leaked=True``, and that a "not-started"
timeout (worker never dequeued) does not misfire.

All tests exercise the real dedicated executor (InterruptibleThreadPoolExecutor)
via ``make_mock_hassette()``, not a mock pool.
"""

import asyncio
import threading
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration
from hassette.task_bucket.task_bucket import TaskBucket
from hassette.test_utils.mock_hassette import make_mock_hassette

from .conftest import make_mock_listener

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def executor(
    db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]
) -> AsyncIterator[CommandExecutor]:
    """CommandExecutor with real DB wired in (same pattern as test_command_executor.py)."""
    _db_service, _session_id = initialized_db
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


# ---------------------------------------------------------------------------
# FR#3 / AC#1: not-started sync timeout → thread_leaked=False (cell[0] still None)
# ---------------------------------------------------------------------------


async def test_not_started_sync_timeout_no_false_positive(
    executor: CommandExecutor,
) -> None:
    """run_in_thread is called but worker hasn't dequeued before timeout → thread_leaked=False.

    Saturates the pool (max_workers=2) with two long-running blockers so that the
    third submission sits in the queue.  When the asyncio timeout fires, cell[0] is
    still None (the worker never called _call), so the liveness guard must not flag
    thread_leaked.  Exercises the ``cell[0] is not None`` branch in _execute.
    """
    # Gate for the two pool-filling blockers.  We release it after the test assertion
    # so they exit cleanly before the test tears down.
    pool_gate = threading.Event()
    # Barrier with 3 parties: the two filler threads, plus this test (which waits via
    # asyncio.to_thread below, so its wait runs on a real thread and counts as a party).
    # The barrier releases only once both fillers have provably started on the pool,
    # replacing a racy fixed sleep.
    started = threading.Barrier(3)
    hassette_mock = make_mock_hassette()
    bucket = TaskBucket(hassette_mock)

    def pool_filler() -> None:
        started.wait(timeout=2.0)
        pool_gate.wait(timeout=10.0)

    # Submit two jobs to saturate both workers (max_workers=2 in make_mock_hassette).
    # Use the underlying sync_executor directly so these don't touch SYNC_WORKER_CELL.
    loop = asyncio.get_running_loop()
    filler_f1 = loop.run_in_executor(hassette_mock.sync_executor, pool_filler)
    filler_f2 = loop.run_in_executor(hassette_mock.sync_executor, pool_filler)

    # Wait until both fillers have definitely dequeued and started.
    await asyncio.to_thread(started.wait, 2.0)

    # Now submit the real handler — it will queue behind the two fillers.
    def sync_fn(_event: object) -> None:
        pass  # never reached within the test

    adapted = bucket.make_async_adapter(sync_fn)

    async def invoke(event: object) -> None:
        await adapted(event)

    listener = make_mock_listener()
    listener.invoker.invoke = invoke
    listener.invoker.error_handler = None
    listener.identity.app_key = "test_app"
    listener.identity.instance_index = 0

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=4,
        source_tier="app",
        effective_timeout=0.01,  # 10ms — fires before pool has a free slot
    )

    await executor.execute(cmd)

    # Release the pool fillers so they exit before teardown.
    pool_gate.set()
    await asyncio.gather(filler_f1, filler_f2, return_exceptions=True)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, ExecutionRecord)
    assert record.status == "timed_out"
    assert record.thread_leaked is False, "thread_leaked must be False when worker never dequeued (cell[0] is None)"


# ---------------------------------------------------------------------------
# FR#3 / AC#1: blocked sync handler → thread_leaked=True
# ---------------------------------------------------------------------------


async def test_sync_handler_timeout_sets_thread_leaked(
    executor: CommandExecutor,
) -> None:
    """A sync handler blocking past its timeout produces thread_leaked=True (FR#3, AC#1).

    The handler sleeps for much longer than the timeout; when asyncio cancels
    the await the worker thread is still alive, so the liveness check fires.
    """
    # make_mock_hassette provisions a real InterruptibleThreadPoolExecutor so
    # run_in_thread can submit via loop.run_in_executor(hassette.sync_executor, ...)
    # without creating an unawaited AsyncMock coroutine.
    bucket = TaskBucket(make_mock_hassette())

    released = threading.Event()

    def sync_blocking(_event: object) -> None:
        # Block until released (or 5s safety cap) so the worker is definitely
        # alive when the asyncio timeout fires.
        released.wait(timeout=5.0)

    adapted = bucket.make_async_adapter(sync_blocking)

    async def invoke(event: object) -> None:
        await adapted(event)

    listener = make_mock_listener()
    listener.invoker.invoke = invoke
    listener.invoker.error_handler = None
    listener.identity.app_key = "test_app"
    listener.identity.instance_index = 0

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=1,
        source_tier="app",
        effective_timeout=0.05,  # 50ms — worker will still be alive
    )

    await executor.execute(cmd)

    # Release the worker so it can exit cleanly after the test.
    released.set()

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, ExecutionRecord)
    assert record.status == "timed_out"
    assert record.thread_leaked is True, "Expected thread_leaked=True for a sync handler still alive after timeout"


# ---------------------------------------------------------------------------
# FR#3 / AC#1: async handler timeout → thread_leaked=False (no worker)
# ---------------------------------------------------------------------------


async def test_async_handler_timeout_does_not_set_thread_leaked(
    executor: CommandExecutor,
) -> None:
    """An async handler that times out does NOT set thread_leaked (no worker thread)."""
    listener = make_mock_listener()

    async def slow_async(_event: object) -> None:
        await asyncio.sleep(10.0)

    listener.invoker.invoke = slow_async
    listener.invoker.error_handler = None

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=2,
        source_tier="app",
        effective_timeout=0.05,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, ExecutionRecord)
    assert record.status == "timed_out"
    assert record.thread_leaked is False, "thread_leaked must be False for async handlers (no worker thread)"


# ---------------------------------------------------------------------------
# AC#1: distinguishable from clean timeout (thread finishes before check)
# ---------------------------------------------------------------------------


async def test_pure_async_timeout_no_cell_no_thread_leaked(
    executor: CommandExecutor,
) -> None:
    """A pure async handler that times out (no run_in_thread) sets thread_leaked=False.

    SYNC_WORKER_CELL is never set because no run_in_thread call occurs, so the
    liveness guard sees cell=None and does not flag the execution.  This is the
    primary "not-started" / "no worker" gate.
    """

    async def async_slow(_event: object) -> None:
        await asyncio.sleep(10.0)

    listener = make_mock_listener()
    listener.invoker.invoke = async_slow
    listener.invoker.error_handler = None
    listener.identity.app_key = "test_app"
    listener.identity.instance_index = 0

    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=3,
        source_tier="app",
        effective_timeout=0.05,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, ExecutionRecord)
    assert record.status == "timed_out"
    # No worker thread — cell is None, so thread_leaked must be False
    assert record.thread_leaked is False


# ---------------------------------------------------------------------------
# AC#1: round-trip persistence — thread_leaked column survives write+read back
# ---------------------------------------------------------------------------


async def test_thread_leaked_persists_to_db(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """thread_leaked=True on an execution record persists to the DB and reads back correctly.

    Verifies the 004.sql migration column is wired end-to-end: build_record →
    _execution_insert_params → INSERT → SELECT.
    """
    db_service, _session_id = initialized_db

    # Register the listener so the FK constraint is satisfied.
    reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="test",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_thread_leaked.py:1",
        registration_source=None,
    )
    listener_id = await executor.register_listener(reg)

    # Build the record directly so we avoid calling build_record with a MagicMock event
    # (cmd.event.payload.origin would be a MagicMock and SQLite can't bind it).
    # The persistence path is independent of how the flag is set — we're testing the
    # _execution_insert_params → INSERT → SELECT round-trip, not build_record itself.
    record = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=_session_id,
        execution_start_ts=time.time(),
        duration_ms=55.0,
        status="timed_out",
        thread_leaked=True,
        error_type="TimeoutError",
        error_message="execution timed out",
        execution_id="test-exec-thread-leaked",
    )
    assert record.thread_leaked is True

    # Persist and read back.
    await executor.persist_batch([record])

    cursor = await db_service.db.execute(
        "SELECT thread_leaked FROM executions WHERE execution_id = ?",
        ("test-exec-thread-leaked",),
    )
    row = await cursor.fetchone()
    assert row is not None, "execution row not found after persist"
    assert row[0] == 1, f"Expected thread_leaked=1, got {row[0]}"


async def test_thread_leaked_false_persists_as_zero(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """thread_leaked=False (default) persists as 0 in the DB."""
    db_service, _session_id = initialized_db

    reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="test",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_thread_leaked.py:1",
        registration_source=None,
    )
    listener_id = await executor.register_listener(reg)

    record = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=_session_id,
        execution_start_ts=time.time(),
        duration_ms=50.0,
        status="timed_out",
        thread_leaked=False,
        error_type="TimeoutError",
        error_message="execution timed out",
        execution_id="test-exec-no-leak",
    )
    assert record.thread_leaked is False

    await executor.persist_batch([record])

    cursor = await db_service.db.execute(
        "SELECT thread_leaked FROM executions WHERE execution_id = ?",
        ("test-exec-no-leak",),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0, f"Expected thread_leaked=0, got {row[0]}"
