"""Integration tests for CommandExecutor with real SQLite database."""

import asyncio
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.exceptions import DependencyError, HassetteError
from hassette.scheduler.classes import JobExecutionRecord, ScheduledJob
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.utils.execution import ExecutionResult


@pytest.fixture
async def executor(
    db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]
) -> AsyncIterator[CommandExecutor]:
    """Create and prepare a CommandExecutor with real DB wired in."""
    _db_service, _session_id = initialized_db
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    try:
        yield exc
    finally:
        await exc.on_shutdown()


def make_listener_registration(*, topic: str = "hass.event.state_changed") -> ListenerRegistration:
    return ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic=topic,
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_command_executor.py:1",
        registration_source=None,
    )


def make_job_registration(*, job_name: str = "test_job") -> ScheduledJobRegistration:
    return ScheduledJobRegistration(
        app_key="test_app",
        instance_index=0,
        job_name=job_name,
        handler_method="test_app.my_job",
        trigger_type=None,
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_command_executor.py:1",
        registration_source=None,
    )


def make_mock_listener() -> MagicMock:
    """Return a mock Listener whose invoke() is an awaitable coroutine."""
    listener = MagicMock()
    listener.invoke = AsyncMock()
    listener.invoker.invoke = AsyncMock()
    listener.error_handler = None
    listener.invoker.error_handler = None
    return listener


def make_mock_job() -> MagicMock:
    """Return a mock ScheduledJob."""
    job = MagicMock(spec=ScheduledJob)
    job.error_handler = None
    return job


async def test_cancelled_error_reraises(executor: CommandExecutor) -> None:
    """CancelledError must be re-raised after queueing a 'cancelled' record."""
    listener = make_mock_listener()
    listener.invoke.side_effect = asyncio.CancelledError()
    listener.invoker.invoke.side_effect = asyncio.CancelledError()

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(cmd)

    # Record should have been queued
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "cancelled"
    assert record.listener_id == 1


async def test_dependency_error_swallowed(executor: CommandExecutor) -> None:
    """DependencyError must be swallowed (not re-raised) and logged as error."""
    listener = make_mock_listener()
    listener.invoke.side_effect = DependencyError("missing dep")
    listener.invoker.invoke.side_effect = DependencyError("missing dep")

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    # Should not raise
    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "error"
    assert record.error_type == "DependencyError"
    assert record.error_message == "missing dep"
    # DependencyError should NOT include traceback (logger.error, not logger.exception)
    # We can't easily assert logger call, but we verify the record has no traceback
    assert record.error_traceback is None


async def test_hassette_error_swallowed(executor: CommandExecutor) -> None:
    """HassetteError must be swallowed and logged without traceback."""
    listener = make_mock_listener()
    listener.invoke.side_effect = HassetteError("framework error")
    listener.invoker.invoke.side_effect = HassetteError("framework error")

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "error"
    assert record.error_type == "HassetteError"
    assert record.error_message == "framework error"
    assert record.error_traceback is None


async def test_unexpected_error_swallowed(executor: CommandExecutor) -> None:
    """Generic Exception must be swallowed and include traceback."""
    listener = make_mock_listener()
    listener.invoke.side_effect = ValueError("oops")
    listener.invoker.invoke.side_effect = ValueError("oops")

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "error"
    assert record.error_type == "ValueError"
    assert record.error_message == "oops"
    # logger.exception includes traceback — we verify it was stored
    assert record.error_traceback is not None
    assert "ValueError" in record.error_traceback


async def test_success_record_queued(executor: CommandExecutor) -> None:
    """Successful invocation must queue a 'success' record."""
    listener = make_mock_listener()
    listener.invoke.return_value = None
    listener.invoker.invoke.return_value = None

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "success"
    assert record.listener_id == 1
    assert record.error_type is None
    assert record.error_message is None
    assert record.error_traceback is None
    assert record.duration_ms >= 0


async def test_execute_timeout_fires(executor: CommandExecutor) -> None:
    """Handler exceeding timeout produces 'timed_out' record."""

    async def slow_handler(_event):
        await asyncio.sleep(10)

    listener = make_mock_listener()
    listener.invoke = slow_handler
    listener.invoker.invoke = slow_handler

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=0.05
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "timed_out"


async def test_execute_timeout_none_is_noop(executor: CommandExecutor) -> None:
    """effective_timeout=None does not enforce timeout."""
    listener = make_mock_listener()
    listener.invoke.return_value = None
    listener.invoker.invoke.return_value = None

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=1, source_tier="app", effective_timeout=None
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "success"


async def test_timeout_warning_rate_limited(executor: CommandExecutor) -> None:
    """Multiple rapid timeouts produce at most one WARNING per 60s window."""

    async def slow_handler(_event):
        await asyncio.sleep(10)

    listener = make_mock_listener()
    listener.invoke = slow_handler
    listener.invoker.invoke = slow_handler

    warnings_logged: list[str] = []
    original_warning = executor.logger.warning

    def capture_warning(msg, *args):
        warnings_logged.append(msg % args if args else msg)

    executor.logger.warning = capture_warning  # pyright: ignore[reportAttributeAccessIssue]

    # Fire 3 timeouts with the same listener_id
    for _ in range(3):
        cmd = InvokeHandler(
            listener=listener,
            event=MagicMock(),
            topic="test",
            listener_id=1,
            source_tier="app",
            effective_timeout=0.01,
        )
        await executor.execute(cmd)

    executor.logger.warning = original_warning  # pyright: ignore[reportAttributeAccessIssue]

    # Only one timeout warning should have been logged (rate-limited by listener_id)
    timeout_warnings = [w for w in warnings_logged if "timed out" in w.lower() or "timeout" in w.lower()]
    assert len(timeout_warnings) == 1, f"Expected 1 timeout warning, got {len(timeout_warnings)}: {timeout_warnings}"


async def test_timeout_warning_lazy_eviction(executor: CommandExecutor) -> None:
    """Stale entries are evicted during rate-limit check."""

    async def slow_handler(_event):
        await asyncio.sleep(10)

    listener = make_mock_listener()
    listener.invoke = slow_handler
    listener.invoker.invoke = slow_handler

    # Manually seed a stale entry (>60s ago)
    executor._timeout_warn_timestamps = {1: time.monotonic() - 120.0}  # pyright: ignore[reportAttributeAccessIssue]

    # Fire a timeout for a different listener_id
    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="test",
        listener_id=2,
        source_tier="app",
        effective_timeout=0.01,
    )
    await executor.execute(cmd)

    # Stale entry for listener_id=1 should have been evicted
    assert 1 not in executor._timeout_warn_timestamps


async def test_serve_drains_queue_to_db(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """Records placed in the write queue appear in handler_invocations after drain."""
    db_service, session_id = initialized_db

    # First register a listener to get a valid listener_id FK
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    # Queue a success record directly
    record = HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=10.0,
        status="success",
        error_type=None,
        error_message=None,
        error_traceback=None,
    )
    executor._write_queue.put_nowait(record)

    # Drain without going through serve() loop — call _drain_and_persist directly
    await executor._drain_and_persist()

    # Verify it landed in DB
    cursor = await db_service.db.execute(
        "SELECT status, listener_id, session_id FROM handler_invocations WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "success"
    assert rows[0][1] == listener_id
    assert rows[0][2] == session_id


async def test_flush_queue_on_shutdown(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """_flush_queue() persists remaining records before returning."""
    db_service, session_id = initialized_db

    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    # Put two records in the queue
    for _ in range(2):
        record = HandlerInvocationRecord(
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=time.time(),
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
        )
        executor._write_queue.put_nowait(record)

    await executor._flush_queue()

    # Both records should be in DB, queue should be empty
    assert executor._write_queue.empty()

    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM handler_invocations WHERE listener_id = ?",
        (listener_id,),
    )
    row = await cursor.fetchone()
    assert row[0] == 2


async def test_execute_job_success_record_queued(executor: CommandExecutor) -> None:
    """Successful job execution queues a JobExecutionRecord with status='success'."""
    job = make_mock_job()
    callable_mock = AsyncMock(return_value=None)

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42, source_tier="app", effective_timeout=None)
    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.status == "success"
    assert record.job_id == 42
    assert record.duration_ms >= 0


async def test_execute_job_error_swallowed(executor: CommandExecutor) -> None:
    """Job error is swallowed and queues a JobExecutionRecord with status='error'."""
    job = make_mock_job()
    callable_mock = AsyncMock(side_effect=RuntimeError("job failed"))

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42, source_tier="app", effective_timeout=None)
    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.status == "error"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "job failed"
    assert record.error_traceback is not None


def test_build_record_uses_session_id_directly(db_hassette: AsyncMock) -> None:
    """_build_record() reads session_id from self.hassette.session_id directly.

    _safe_session_id() was removed in WP03. session_id is now always read directly.
    The phased startup contract guarantees a valid session_id exists before any
    handler can fire, so RuntimeError from session_id is a programming error.
    """
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    db_hassette.session_id = 99

    listener = make_mock_listener()

    cmd = InvokeHandler(
        listener=listener, event=MagicMock(), topic="test", listener_id=5, source_tier="app", effective_timeout=None
    )
    result = ExecutionResult()
    result.status = "success"
    result.duration_ms = 1.0

    record = exc._build_record(cmd, result, time.time(), "test-exec-id")
    assert isinstance(record, HandlerInvocationRecord)
    assert record.session_id == 99
    assert record.listener_id == 5


async def test_persist_batch_drops_presession_records(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """_persist_batch() silently drops records with session_id=0 (FK sentinel).

    Regression: records queued before _create_session() runs would have violated
    the sessions FK constraint. The 0-sentinel matches the existing listener_id=0
    pattern for the registration race.
    """
    db_service, session_id = initialized_db
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    now = time.time()
    valid = HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
        error_type=None,
        error_message=None,
        error_traceback=None,
    )
    pre_session = HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=0,  # startup race sentinel
        execution_start_ts=now,
        duration_ms=3.0,
        status="success",
        error_type=None,
        error_message=None,
        error_traceback=None,
    )

    await executor._persist_batch([valid, pre_session], [])

    cursor = await db_service.db.execute(
        "SELECT session_id FROM handler_invocations WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    # Only the valid record written — pre-session record silently dropped
    assert len(rows) == 1
    assert rows[0][0] == session_id


async def test_register_listener_blocks_until_database_ready(
    db_hassette: AsyncMock,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """register_listener() waits for DatabaseService before accessing .db.

    Regression: BusService fires register_listener() as a background task immediately
    on add_listener(), before CommandExecutor.on_initialize() completes. Previously
    this crashed with RuntimeError("Database connection is not initialized").
    """
    db_service, _ = initialized_db

    db_ready = asyncio.Event()

    async def gated_wait(resources: list) -> bool:
        if db_service in resources:
            await db_ready.wait()
        return True

    db_hassette.wait_for_ready = gated_wait
    exc = CommandExecutor(db_hassette, parent=db_hassette)

    task = asyncio.create_task(exc.register_listener(make_listener_registration()))
    await asyncio.sleep(0)
    assert not task.done(), "register_listener should block while DatabaseService is not ready"

    db_ready.set()
    listener_id = await asyncio.wait_for(task, timeout=1.0)
    assert listener_id > 0


async def test_register_job_blocks_until_database_ready(
    db_hassette: AsyncMock,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """register_job() waits for DatabaseService before accessing .db.

    Regression: same race as register_listener — SchedulerService fires register_job()
    as a background task before the DB is ready.
    """
    db_service, _ = initialized_db

    db_ready = asyncio.Event()

    async def gated_wait(resources: list) -> bool:
        if db_service in resources:
            await db_ready.wait()
        return True

    db_hassette.wait_for_ready = gated_wait
    exc = CommandExecutor(db_hassette, parent=db_hassette)

    task = asyncio.create_task(exc.register_job(make_job_registration()))
    await asyncio.sleep(0)
    assert not task.done(), "register_job should block while DatabaseService is not ready"

    db_ready.set()
    job_id = await asyncio.wait_for(task, timeout=1.0)
    assert job_id > 0


async def test_concurrent_registrations_do_not_raise(
    db_hassette: AsyncMock,
) -> None:
    """N concurrent register_listener() calls complete without OperationalError.

    Regression: before routing writes through database_service.submit(), concurrent
    callers each called db.execute() + db.commit() directly on the same aiosqlite
    connection, causing 'cannot start a transaction within a transaction' OperationalError.

    After the fix, all writes are serialized through the DatabaseService worker, so
    concurrent callers wait their turn and every call returns a valid positive ID.
    """
    db_service = DatabaseService(db_hassette, parent=db_hassette)
    await db_service.on_initialize()
    db_hassette.database_service = db_service

    try:
        exc = CommandExecutor(db_hassette, parent=db_hassette)
        await exc.on_initialize()

        batch_size = 10
        regs = [make_listener_registration(topic=f"test.topic.{i}") for i in range(batch_size)]

        ids = await asyncio.gather(*[exc.register_listener(reg) for reg in regs])

        assert len(ids) == batch_size
        assert all(isinstance(id_, int) and id_ > 0 for id_ in ids), f"All IDs must be positive ints, got: {ids}"
    finally:
        await db_service.on_shutdown()


async def test_fk_preserved_across_restart(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """Upsert same natural key across simulated restarts preserves FK from invocations.

    Regression: before upsert, clear_registrations() deleted the row and re-INSERT
    created a new ID, orphaning historical handler_invocations rows.
    """
    db_service, session_id = initialized_db

    # Register listener (first "session")
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)
    assert listener_id > 0

    # Create an invocation history row
    await db_service.db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db_service.db.commit()

    # Simulate restart: re-register with same natural key (upsert)
    new_id = await executor.register_listener(reg)

    # Must return the SAME ID — FK reference in handler_invocations is preserved
    assert new_id == listener_id, (
        f"Re-registration must return the same listener_id={listener_id}, got {new_id}. "
        "FK references from handler_invocations would be orphaned if the ID changes."
    )

    # Verify the invocation still references the same listener
    cursor = await db_service.db.execute(
        "SELECT listener_id FROM handler_invocations WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == listener_id


async def test_reconciliation_ordering(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """reconcile_registrations() correctly retires stale rows after re-registration.

    This replaces the deleted clear_registrations test and verifies the post-ready
    reconciliation contract: stale rows (not in live_ids) are retired/deleted, while
    live rows are preserved.
    """
    db_service, session_id = initialized_db

    # Register two listeners
    reg_a = make_listener_registration(topic="topic.a")
    reg_b = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event_b",
        topic="topic.b",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
    )
    id_a = await executor.register_listener(reg_a)
    id_b = await executor.register_listener(reg_b)

    # Create history for id_b (so it gets retired, not deleted)
    await db_service.db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (id_b, session_id, time.time(), 1.0, "success"),
    )
    await db_service.db.commit()

    # Reconcile: only id_a is live; id_b is stale but has history
    await executor.reconcile_registrations("test_app", [id_a], [], session_id=session_id)

    # id_a should be untouched
    cursor = await db_service.db.execute("SELECT retired_at FROM listeners WHERE id = ?", (id_a,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "Live listener should not be retired"

    # id_b should be retired (has history)
    cursor = await db_service.db.execute("SELECT retired_at FROM listeners WHERE id = ?", (id_b,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Stale listener with history should be retired"
