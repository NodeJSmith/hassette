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
        if db_service._db is not None:
            await db_service._db.close()
            db_service._db = None


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
    now = time.time()
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
        source_location="test_command_executor.py:1",
        registration_source=None,
        first_registered_at=now,
        last_registered_at=now,
    )


def _make_job_registration(*, job_name: str = "test_job") -> ScheduledJobRegistration:
    now = time.time()
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
        first_registered_at=now,
        last_registered_at=now,
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
async def test_register_listener_upsert(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """register_listener() inserts on first call, updates last_registered_at on second."""
    db_service, _ = initialized_db
    reg = _make_listener_registration()
    first_id = await executor.register_listener(reg)

    # Fetch first_registered_at
    cursor = await db_service.db.execute(
        "SELECT first_registered_at, last_registered_at FROM listeners WHERE id = ?",
        (first_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    first_registered_at_before = row[0]
    last_registered_at_before = row[1]

    # Wait a bit so last_registered_at will be different
    await asyncio.sleep(0.01)

    # Second registration with updated last_registered_at
    now = time.time()
    reg2 = ListenerRegistration(
        **{**reg.__dict__, "last_registered_at": now},
    )
    await executor.register_listener(reg2)

    # Check that there's still only 1 row (upsert, not insert)
    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM listeners WHERE app_key = ? AND handler_method = ? AND topic = ?",
        (reg.app_key, reg.handler_method, reg.topic),
    )
    count_row = await cursor.fetchone()
    assert count_row[0] == 1

    # first_registered_at must NOT change
    cursor = await db_service.db.execute(
        "SELECT first_registered_at, last_registered_at FROM listeners WHERE id = ?",
        (first_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == first_registered_at_before, "first_registered_at must not change on conflict"
    assert row[1] >= last_registered_at_before, "last_registered_at must update"


@pytest.mark.asyncio
async def test_register_job_upsert(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """register_job() inserts on first call, updates last_registered_at on second."""
    db_service, _ = initialized_db
    reg = _make_job_registration()
    first_id = await executor.register_job(reg)

    cursor = await db_service.db.execute(
        "SELECT first_registered_at, last_registered_at FROM scheduled_jobs WHERE id = ?",
        (first_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    first_ts = row[0]

    await asyncio.sleep(0.01)
    now = time.time()
    reg2 = ScheduledJobRegistration(
        **{**reg.__dict__, "last_registered_at": now},
    )
    await executor.register_job(reg2)

    # Still only 1 row
    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM scheduled_jobs WHERE app_key = ? AND job_name = ?",
        (reg.app_key, reg.job_name),
    )
    count_row = await cursor.fetchone()
    assert count_row[0] == 1

    # first_registered_at unchanged
    cursor = await db_service.db.execute(
        "SELECT first_registered_at FROM scheduled_jobs WHERE id = ?",
        (first_id,),
    )
    row = await cursor.fetchone()
    assert row[0] == first_ts


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
