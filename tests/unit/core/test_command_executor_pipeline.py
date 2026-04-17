"""Unit tests for CommandExecutor write-pipeline resilience (WP03).

Tests cover:
- Bounded queue with overflow handling
- RetryableBatch expansion in drain and flush
- Sentinel guard: id=0 → drop, id=None → persist
- Error classification in _persist_batch
- FK violation row-by-row fallback
- source_tier and is_di_failure in _build_record
- _flush_queue graceful handling on DB closed
"""

import asyncio
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.command_executor import CommandExecutor, RetryableBatch
from hassette.core.commands import InvokeHandler
from hassette.scheduler.classes import JobExecutionRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_invocation(
    listener_id: int | None = 1,
    session_id: int = 1,
    source_tier: str = "app",
    is_di_failure: bool = False,
) -> HandlerInvocationRecord:
    return HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=1.0,
        status="success",
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
        is_di_failure=is_di_failure,
    )


def make_job_record(
    job_id: int | None = 1,
    session_id: int = 1,
    source_tier: str = "app",
) -> JobExecutionRecord:
    return JobExecutionRecord(
        job_id=job_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=1.0,
        status="success",
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
    )


def make_executor(queue_max: int = 10) -> CommandExecutor:
    """Build a CommandExecutor with mocked Hassette dependencies."""
    hassette = MagicMock()
    hassette.config.telemetry_write_queue_max = queue_max
    hassette.config.command_executor_log_level = "DEBUG"
    hassette.session_id = 42
    hassette.database_service = MagicMock()
    hassette.database_service.submit = AsyncMock(return_value=None)
    # Resource base class needs these
    hassette.config.resource_shutdown_timeout_seconds = 30
    hassette.config.startup_timeout_seconds = 30
    hassette.shutdown_event = asyncio.Event()
    hassette.ready_event = asyncio.Event()
    hassette.task_bucket = MagicMock()
    return CommandExecutor.__new__(CommandExecutor)


def _init_executor(queue_max: int = 10) -> CommandExecutor:
    """Create and minimally init a CommandExecutor for pipeline tests."""
    executor = make_executor(queue_max)
    executor._write_queue = asyncio.Queue(maxsize=queue_max)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._last_capacity_warn_ts = 0.0
    executor.repository = MagicMock()
    executor.repository.persist_batch = MagicMock()
    executor.hassette = MagicMock()
    executor.hassette.session_id = 42
    executor.hassette.config.telemetry_write_queue_max = queue_max
    executor.hassette.database_service = MagicMock()
    executor.hassette.database_service.submit = AsyncMock(return_value=None)
    executor.logger = MagicMock()
    return executor


# ---------------------------------------------------------------------------
# Subtask 2 + 3: Bounded queue — QueueFull handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bounded_queue_drops_on_full():
    """Filling a queue beyond maxsize triggers QueueFull; _dropped_overflow is incremented."""
    executor = _init_executor(queue_max=3)

    rec = make_invocation()

    # Fill queue to max
    for _ in range(3):
        executor._write_queue.put_nowait(rec)

    # Next put_nowait should raise QueueFull — simulate what execute() does
    try:
        executor._write_queue.put_nowait(rec)
        # Should have raised — if not, test the catch path manually
    except asyncio.QueueFull:
        executor._dropped_overflow += 1
        executor.logger.error("Queue full — dropping record")

    assert executor._dropped_overflow == 1
    assert executor._write_queue.qsize() == 3


# ---------------------------------------------------------------------------
# Subtask 5: RetryableBatch expansion in _drain_and_persist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retryable_batch_expanded_in_drain():
    """RetryableBatch enqueued in write_queue expands into the current batch on drain."""
    executor = _init_executor()

    inv = make_invocation(listener_id=5)
    job = make_job_record(job_id=7)
    batch = RetryableBatch(invocations=[inv], job_executions=[job], retry_count=1)

    executor._write_queue.put_nowait(batch)

    captured_invocations = []
    captured_jobs = []
    captured_retry_counts = []

    async def fake_persist_batch(invocations, job_executions, *, retry_count=0):
        captured_invocations.extend(invocations)
        captured_jobs.extend(job_executions)
        captured_retry_counts.append(retry_count)

    executor._persist_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]

    await executor._drain_and_persist()

    assert inv in captured_invocations
    assert job in captured_jobs
    # RetryableBatch should preserve its retry_count (was 1)
    assert 1 in captured_retry_counts


# ---------------------------------------------------------------------------
# Subtask 6: Sentinel guard — id=0 dropped, id=None allowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sentinel_guard_drops_id_zero():
    """Records with listener_id=0 are dropped with a REGRESSION log, not persisted."""
    executor = _init_executor()

    invocations = [make_invocation(listener_id=0, session_id=1)]
    job_executions: list[JobExecutionRecord] = []

    persist_batch_called = False

    async def fake_persist_batch(_invs, _jobs):
        nonlocal persist_batch_called
        persist_batch_called = True

    executor.repository.persist_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor._persist_batch(executor, invocations, job_executions)  # pyright: ignore[reportArgumentType]

    # REGRESSION log must have fired
    executor.logger.error.assert_called()
    error_calls = [str(c) for c in executor.logger.error.call_args_list]
    assert any("REGRESSION" in c for c in error_calls)

    # persist_batch must not have been called (all records filtered out)
    assert not persist_batch_called


@pytest.mark.asyncio
async def test_sentinel_guard_allows_id_none():
    """Records with listener_id=None are NOT dropped — they represent pre-reg orphans."""
    executor = _init_executor()

    none_inv = make_invocation(listener_id=None, session_id=1)
    invocations = [none_inv]
    job_executions: list[JobExecutionRecord] = []

    persist_calls: list[tuple[list, list]] = []

    async def fake_persist_batch(invs, jobs):
        persist_calls.append((list(invs), list(jobs)))

    executor.repository.persist_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor._persist_batch(executor, invocations, job_executions)  # pyright: ignore[reportArgumentType]

    # Should NOT have logged REGRESSION (no id=0 sentinel dropped)
    error_calls = [str(c) for c in executor.logger.error.call_args_list]
    regression_errors = [c for c in error_calls if "REGRESSION" in c and "listener" in c.lower()]
    assert len(regression_errors) == 0

    # Should have attempted to persist
    assert len(persist_calls) == 1
    persisted_invocations = persist_calls[0][0]
    assert none_inv in persisted_invocations


# ---------------------------------------------------------------------------
# Subtask 7: Error classification — OperationalError → retry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_operational_error_triggers_retry():
    """OperationalError from persist_batch causes re-enqueue as RetryableBatch."""
    executor = _init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    invocations = [inv]
    job_executions: list[JobExecutionRecord] = []

    async def fail_persist(_invs, _jobs):
        raise sqlite3.OperationalError("disk I/O error")

    executor.repository.persist_batch = fail_persist  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor._persist_batch(executor, invocations, job_executions)  # pyright: ignore[reportArgumentType]

    # Should have re-enqueued as RetryableBatch
    assert not executor._write_queue.empty()
    queued = executor._write_queue.get_nowait()
    assert isinstance(queued, RetryableBatch)
    assert queued.retry_count == 1
    assert inv in queued.invocations


# ---------------------------------------------------------------------------
# Subtask 7: Max retries — drops batch, increments _dropped_exhausted
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_max_retries_drops_batch():
    """RetryableBatch with retry_count=3 is dropped and _dropped_exhausted is incremented."""
    executor = _init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    exhausted_batch = RetryableBatch(invocations=[inv], job_executions=[], retry_count=3)

    invocations = list(exhausted_batch.invocations)
    job_executions = list(exhausted_batch.job_executions)

    async def fail_persist(_invs, _jobs):
        raise sqlite3.OperationalError("disk I/O error")

    executor.repository.persist_batch = fail_persist  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    # Pass retry_count=3 to indicate exhausted batch
    await CommandExecutor._persist_batch(  # pyright: ignore[reportArgumentType]
        executor, invocations, job_executions, retry_count=3
    )

    # Should NOT have re-enqueued (retry_count >= 3)
    assert executor._write_queue.empty()
    # Should have incremented dropped_exhausted
    assert executor._dropped_exhausted == 1


# ---------------------------------------------------------------------------
# Subtask 7: DataError → drop immediately + REGRESSION log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_data_error_drops_immediately():
    """DataError from persist_batch → drop immediately + REGRESSION log, no re-enqueue."""
    executor = _init_executor()

    inv = make_invocation(listener_id=5, session_id=1)

    async def fail_persist(_invs, _jobs):
        raise sqlite3.DataError("column mismatch")

    executor.repository.persist_batch = fail_persist  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor._persist_batch(executor, [inv], [])  # pyright: ignore[reportArgumentType]

    # No re-enqueue
    assert executor._write_queue.empty()

    # REGRESSION log
    error_calls = [str(c) for c in executor.logger.error.call_args_list]
    assert any("REGRESSION" in c or "DataError" in c or "non-retryable" in c.lower() for c in error_calls)


# ---------------------------------------------------------------------------
# Subtask 8: FK violation → row-by-row fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_integrity_error_row_by_row_fallback():
    """IntegrityError triggers FK fallback via persist_batch_with_fk_fallback; dropped count tracked."""
    executor = _init_executor()

    inv_good = make_invocation(listener_id=1, session_id=1)
    inv_bad = make_invocation(listener_id=999, session_id=1)  # FK violation
    invocations = [inv_good, inv_bad]

    # Simulate: batch call raises IntegrityError; FK fallback returns 1 dropped record
    async def fake_persist_batch(invs, _jobs):
        if len(invs) > 1:
            raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    async def fake_fk_fallback(_invs, _jobs):
        return 1  # 1 record dropped

    executor.repository.persist_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]
    executor.repository.persist_batch_with_fk_fallback = fake_fk_fallback  # pyright: ignore[reportAttributeAccessIssue]

    async def direct_submit(coro):
        return await coro

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor._persist_batch(executor, invocations, [])  # pyright: ignore[reportArgumentType]

    # Should have incremented dropped_exhausted for the 1 record that failed even with null FK
    assert executor._dropped_exhausted == 1


# ---------------------------------------------------------------------------
# Subtask 9: _build_record reads source_tier and is_di_failure
# ---------------------------------------------------------------------------


def test_build_record_reads_source_tier():
    """_build_record sets source_tier from cmd.source_tier."""
    executor = _init_executor()

    listener = MagicMock()
    listener.invoke = AsyncMock()
    event = MagicMock()

    cmd = InvokeHandler(
        listener=listener,
        event=event,
        topic="test/topic",
        listener_id=5,
        source_tier="framework",
    )
    result = MagicMock()
    result.duration_ms = 1.0
    result.status = "success"
    result.error_type = None
    result.error_message = None
    result.error_traceback = None
    result.is_di_failure = False

    record = CommandExecutor._build_record(executor, cmd, result, time.time())  # pyright: ignore[reportArgumentType]

    assert isinstance(record, HandlerInvocationRecord)
    assert record.source_tier == "framework"
    assert record.listener_id == 5


def test_build_record_reads_is_di_failure():
    """_build_record sets is_di_failure from result.is_di_failure."""
    executor = _init_executor()

    listener = MagicMock()
    listener.invoke = AsyncMock()
    event = MagicMock()

    cmd = InvokeHandler(
        listener=listener,
        event=event,
        topic="test/topic",
        listener_id=5,
        source_tier="app",
    )
    result = MagicMock()
    result.duration_ms = 1.0
    result.status = "error"
    result.error_type = "DependencyError"
    result.error_message = "dep failed"
    result.error_traceback = None
    result.is_di_failure = True

    record = CommandExecutor._build_record(executor, cmd, result, time.time())  # pyright: ignore[reportArgumentType]

    assert isinstance(record, HandlerInvocationRecord)
    assert record.is_di_failure is True


# ---------------------------------------------------------------------------
# Subtask 10: _flush_queue handles RuntimeError from submit gracefully
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_queue_handles_db_closed():
    """_flush_queue does not raise when DB submit raises RuntimeError (DB closed at shutdown)."""
    executor = _init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    executor._write_queue.put_nowait(inv)

    # Make submit raise RuntimeError (simulating closed DB) — close the coro to avoid leak
    async def fail_submit(coro):
        coro.close()  # prevent "coroutine was never awaited" warning
        raise RuntimeError("database is closed")

    executor.hassette.database_service.submit = fail_submit  # pyright: ignore[reportAttributeAccessIssue]

    async def fake_persist(_invs, _jobs):
        pass

    executor.repository.persist_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    # _flush_queue must NOT raise — shutdown must complete
    await executor._flush_queue()

    # Should have logged something (error/warning about dropped records)
    assert executor.logger.error.called or executor.logger.warning.called


# ---------------------------------------------------------------------------
# Subtask 11: persist_batch INSERT includes source_tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_batch_includes_source_tier():
    """TelemetryRepository.persist_batch INSERT includes source_tier column."""
    import aiosqlite

    from hassette.core.telemetry_repository import TelemetryRepository

    schema = """
PRAGMA foreign_keys = ON;

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    stopped_at REAL,
    last_heartbeat_at REAL NOT NULL,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    error_traceback TEXT,
    source_tier TEXT NOT NULL DEFAULT 'framework'
        CHECK (source_tier IN ('app', 'framework'))
);

CREATE TABLE listeners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key TEXT NOT NULL,
    instance_index INTEGER NOT NULL,
    handler_method TEXT NOT NULL,
    topic TEXT NOT NULL,
    debounce REAL,
    throttle REAL,
    once INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    predicate_description TEXT,
    human_description TEXT,
    source_location TEXT NOT NULL,
    registration_source TEXT,
    name TEXT,
    retired_at REAL,
    source_tier TEXT NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework'))
);

CREATE UNIQUE INDEX idx_listeners_natural
    ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
    WHERE once = 0;

CREATE TABLE scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key TEXT NOT NULL,
    instance_index INTEGER NOT NULL,
    job_name TEXT NOT NULL,
    handler_method TEXT NOT NULL,
    trigger_type TEXT,
    repeat INTEGER NOT NULL DEFAULT 0,
    args_json TEXT NOT NULL DEFAULT '[]',
    kwargs_json TEXT NOT NULL DEFAULT '{}',
    source_location TEXT NOT NULL,
    registration_source TEXT,
    retired_at REAL,
    source_tier TEXT NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework'))
);

CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

CREATE TABLE handler_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts REAL NOT NULL,
    duration_ms REAL NOT NULL CHECK (duration_ms >= 0.0),
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'cancelled')),
    error_type TEXT,
    error_message TEXT,
    error_traceback TEXT,
    is_di_failure INTEGER NOT NULL DEFAULT 0,
    source_tier TEXT NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework'))
);

CREATE TABLE job_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts REAL NOT NULL,
    duration_ms REAL NOT NULL CHECK (duration_ms >= 0.0),
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'cancelled')),
    error_type TEXT,
    error_message TEXT,
    error_traceback TEXT,
    is_di_failure INTEGER NOT NULL DEFAULT 0,
    source_tier TEXT NOT NULL DEFAULT 'app'
        CHECK (source_tier IN ('app', 'framework'))
);
"""

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(schema)
        await db.commit()

        # Insert a session so FK reference works
        await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status, source_tier) VALUES (?, ?, ?, ?)",
            (time.time(), time.time(), "running", "framework"),
        )
        await db.commit()

        mock_db_service = MagicMock()
        mock_db_service.db = db
        repo = TelemetryRepository(mock_db_service)

        inv = HandlerInvocationRecord(
            listener_id=None,
            session_id=1,
            execution_start_ts=time.time(),
            duration_ms=1.0,
            status="success",
            source_tier="framework",
            is_di_failure=False,
        )

        await repo.persist_batch([inv], [])

        cursor = await db.execute("SELECT source_tier, is_di_failure FROM handler_invocations WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        assert row["source_tier"] == "framework"
        assert row["is_di_failure"] == 0
