"""Integration tests for CommandExecutor with real SQLite database."""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.scheduler.classes import JobExecutionRecord, ScheduledJob

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config pointing to tmp_path."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.command_executor_log_level = "INFO"
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def initialized_db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a real DatabaseService and create a session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    try:
        now = time.time()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        mock_hassette.session_id = session_id
        await db_service.db.commit()
        mock_hassette.database_service = db_service
        yield db_service, session_id
    finally:
        await db_service.on_shutdown()


@pytest.fixture
async def executor(
    mock_hassette: MagicMock, initialized_db: tuple[DatabaseService, int]
) -> AsyncIterator[CommandExecutor]:
    """Create and prepare a CommandExecutor with real DB wired in."""
    _db_service, _session_id = initialized_db
    # wait_for_ready on the mock should be a no-op
    mock_hassette.wait_for_ready = AsyncMock(return_value=True)
    exc = CommandExecutor(mock_hassette, parent=mock_hassette)
    await exc.on_initialize()
    return exc


def _make_listener_registration(*, topic: str = "hass.event.state_changed") -> ListenerRegistration:
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


def _make_job_registration(*, job_name: str = "test_job") -> ScheduledJobRegistration:
    return ScheduledJobRegistration(
        app_key="test_app",
        instance_index=0,
        job_name=job_name,
        handler_method="test_app.my_job",
        trigger_type=None,
        trigger_value=None,
        repeat=False,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_command_executor.py:1",
        registration_source=None,
    )


def _make_mock_listener() -> MagicMock:
    """Return a mock Listener whose invoke() is an awaitable coroutine."""
    listener = MagicMock()
    listener.invoke = AsyncMock()
    return listener


def _make_mock_job() -> MagicMock:
    """Return a mock ScheduledJob."""
    job = MagicMock(spec=ScheduledJob)
    return job


# ---------------------------------------------------------------------------
# Exception contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancelled_error_reraises(executor: CommandExecutor) -> None:
    """CancelledError must be re-raised after queueing a 'cancelled' record."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = asyncio.CancelledError()

    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(cmd)

    # Record should have been queued
    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "cancelled"
    assert record.listener_id == 1


@pytest.mark.asyncio
async def test_dependency_error_swallowed(executor: CommandExecutor) -> None:
    """DependencyError must be swallowed (not re-raised) and logged as error."""
    from hassette.exceptions import DependencyError

    listener = _make_mock_listener()
    listener.invoke.side_effect = DependencyError("missing dep")

    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

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


@pytest.mark.asyncio
async def test_hassette_error_swallowed(executor: CommandExecutor) -> None:
    """HassetteError must be swallowed and logged without traceback."""
    from hassette.exceptions import HassetteError

    listener = _make_mock_listener()
    listener.invoke.side_effect = HassetteError("framework error")

    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.status == "error"
    assert record.error_type == "HassetteError"
    assert record.error_message == "framework error"
    assert record.error_traceback is None


@pytest.mark.asyncio
async def test_unexpected_error_swallowed(executor: CommandExecutor) -> None:
    """Generic Exception must be swallowed and include traceback."""
    listener = _make_mock_listener()
    listener.invoke.side_effect = ValueError("oops")

    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

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


@pytest.mark.asyncio
async def test_success_record_queued(executor: CommandExecutor) -> None:
    """Successful invocation must queue a 'success' record."""
    listener = _make_mock_listener()
    listener.invoke.return_value = None

    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

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


# ---------------------------------------------------------------------------
# Write queue / DB persistence tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serve_drains_queue_to_db(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """Records placed in the write queue appear in handler_invocations after drain."""
    db_service, session_id = initialized_db

    # First register a listener to get a valid listener_id FK
    reg = _make_listener_registration()
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


@pytest.mark.asyncio
async def test_flush_queue_on_shutdown(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """_flush_queue() persists remaining records before returning."""
    db_service, session_id = initialized_db

    reg = _make_listener_registration()
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


# ---------------------------------------------------------------------------
# Upsert / idempotency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_listener_creates_separate_rows(
    executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]
) -> None:
    """register_listener() creates a new row for each call (no upsert)."""
    db_service, _ = initialized_db
    reg = _make_listener_registration()
    first_id = await executor.register_listener(reg)
    second_id = await executor.register_listener(reg)

    assert first_id != second_id

    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM listeners WHERE app_key = ? AND handler_method = ? AND topic = ?",
        (reg.app_key, reg.handler_method, reg.topic),
    )
    count_row = await cursor.fetchone()
    assert count_row[0] == 2


@pytest.mark.asyncio
async def test_register_job_creates_separate_rows(
    executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]
) -> None:
    """register_job() creates a new row for each call (no upsert)."""
    db_service, _ = initialized_db
    reg = _make_job_registration()
    first_id = await executor.register_job(reg)
    second_id = await executor.register_job(reg)

    assert first_id != second_id

    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM scheduled_jobs WHERE app_key = ? AND job_name = ?",
        (reg.app_key, reg.job_name),
    )
    count_row = await cursor.fetchone()
    assert count_row[0] == 2


# ---------------------------------------------------------------------------
# Job execution tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_job_success_record_queued(executor: CommandExecutor) -> None:
    """Successful job execution queues a JobExecutionRecord with status='success'."""
    job = _make_mock_job()
    callable_mock = AsyncMock(return_value=None)

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42)
    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.status == "success"
    assert record.job_id == 42
    assert record.duration_ms >= 0


@pytest.mark.asyncio
async def test_execute_job_error_swallowed(executor: CommandExecutor) -> None:
    """Job error is swallowed and queues a JobExecutionRecord with status='error'."""
    job = _make_mock_job()
    callable_mock = AsyncMock(side_effect=RuntimeError("job failed"))

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42)
    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.status == "error"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "job failed"
    assert record.error_traceback is not None


# ---------------------------------------------------------------------------
# Startup race regression tests
# ---------------------------------------------------------------------------


def test_safe_session_id_returns_zero_and_logs_on_missing_session(mock_hassette: MagicMock) -> None:
    """_safe_session_id() falls back to 0 when no session exists.

    Returns 0 (sentinel) so exception handlers don't crash cascade.
    The persist guard drops the record and logs at ERROR.
    """

    class _NoSession:
        @property
        def session_id(self) -> int:
            raise RuntimeError("No active session")

    exc = CommandExecutor(mock_hassette, parent=mock_hassette)
    exc.hassette = _NoSession()  # pyright: ignore[reportAttributeAccessIssue]
    assert exc._safe_session_id() == 0


@pytest.mark.asyncio
async def test_execute_queues_sentinel_record_when_no_session(executor: CommandExecutor) -> None:
    """execute() queues a record with session_id=0 when session is unavailable.

    Does not crash — the persist guard drops the record at write time.
    """

    class _NoSession:
        @property
        def session_id(self) -> int:
            raise RuntimeError("No active session")

    executor.hassette = _NoSession()  # pyright: ignore[reportAttributeAccessIssue]

    listener = _make_mock_listener()
    cmd = InvokeHandler(listener=listener, event=MagicMock(), topic="test", listener_id=1)

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.session_id == 0


@pytest.mark.asyncio
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
    reg = _make_listener_registration()
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


@pytest.mark.asyncio
async def test_register_listener_blocks_until_database_ready(
    mock_hassette: MagicMock,
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

    mock_hassette.wait_for_ready = gated_wait
    exc = CommandExecutor(mock_hassette, parent=mock_hassette)

    task = asyncio.create_task(exc.register_listener(_make_listener_registration()))
    await asyncio.sleep(0)
    assert not task.done(), "register_listener should block while DatabaseService is not ready"

    db_ready.set()
    listener_id = await asyncio.wait_for(task, timeout=1.0)
    assert listener_id > 0


@pytest.mark.asyncio
async def test_register_job_blocks_until_database_ready(
    mock_hassette: MagicMock,
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

    mock_hassette.wait_for_ready = gated_wait
    exc = CommandExecutor(mock_hassette, parent=mock_hassette)

    task = asyncio.create_task(exc.register_job(_make_job_registration()))
    await asyncio.sleep(0)
    assert not task.done(), "register_job should block while DatabaseService is not ready"

    db_ready.set()
    job_id = await asyncio.wait_for(task, timeout=1.0)
    assert job_id > 0


@pytest.mark.asyncio
async def test_concurrent_registrations_do_not_raise(
    mock_hassette: MagicMock,
    tmp_path: Path,
) -> None:
    """N concurrent register_listener() calls complete without OperationalError.

    Regression: before routing writes through database_service.submit(), concurrent
    callers each called db.execute() + db.commit() directly on the same aiosqlite
    connection, causing 'cannot start a transaction within a transaction' OperationalError.

    After the fix, all writes are serialized through the DatabaseService worker, so
    concurrent callers wait their turn and every call returns a valid positive ID.
    """
    mock_hassette.config.data_dir = tmp_path
    mock_hassette.config.db_path = None
    mock_hassette.config.db_retention_days = 7
    mock_hassette.config.db_migration_timeout_seconds = 120
    mock_hassette.config.db_max_size_mb = 0
    mock_hassette.config.database_service_log_level = "INFO"
    mock_hassette.config.log_level = "INFO"
    mock_hassette.config.task_bucket_log_level = "INFO"
    mock_hassette.config.resource_shutdown_timeout_seconds = 5
    mock_hassette.config.task_cancellation_timeout_seconds = 5
    mock_hassette.config.command_executor_log_level = "INFO"
    mock_hassette.ready_event = asyncio.Event()

    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    mock_hassette.database_service = db_service
    mock_hassette.wait_for_ready = AsyncMock(return_value=True)

    try:
        exc = CommandExecutor(mock_hassette, parent=mock_hassette)
        await exc.on_initialize()

        batch_size = 10
        regs = [_make_listener_registration(topic=f"test.topic.{i}") for i in range(batch_size)]

        ids = await asyncio.gather(*[exc.register_listener(reg) for reg in regs])

        assert len(ids) == batch_size
        assert all(isinstance(id_, int) and id_ > 0 for id_ in ids), f"All IDs must be positive ints, got: {ids}"
    finally:
        await db_service.on_shutdown()
