"""Integration tests for CommandExecutor with real SQLite database."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from hassette.commands import ExecuteJob
from hassette.core import execution_pipeline
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.execution_record_builder import build_execution_record
from hassette.exceptions import DependencyError, HassetteError
from hassette.types.types import ExecutionStatus
from hassette.utils.execution import ExecutionResult
from tests.support.factories import (
    make_execution_record,
    make_job_registration,
    make_listener_registration,
    make_mock_listener,
)

from .conftest import invoke_cmd, make_mock_job, pop_execution_record


def queue_record(
    executor: CommandExecutor,
    listener_id: int,
    session_id: int,
    *,
    status: ExecutionStatus = "success",
    duration_ms: float = 10.0,
) -> None:
    """Put one handler execution record straight onto the executor's write queue.

    ``execution_id`` stays None so a caller can queue several records without tripping the
    UNIQUE constraint on that column.
    """
    executor._write_queue.put_nowait(
        make_execution_record(
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=time.time(),
            duration_ms=duration_ms,
            status=status,
            execution_id=None,
        )
    )


async def test_cancelled_error_reraises(executor: CommandExecutor) -> None:
    """CancelledError must be re-raised after queueing a 'cancelled' record."""
    listener = make_mock_listener(invoke_side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(invoke_cmd(listener))

    # Record should have been queued
    record = pop_execution_record(executor)
    assert record.status == "cancelled"
    assert record.listener_id == 1


async def test_restart_cancellation_persists_cancelled_row(
    executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]
) -> None:
    """A cancelled invocation lands as a status='cancelled' execution row.

    ``restart`` mode cancels the in-flight child task, surfacing as ``CancelledError`` inside the
    handler invocation. ``test_cancelled_error_reraises`` proves that path queues a
    ``status='cancelled'`` record; this test proves such a record persists to the ``executions``
    table — no new mechanism, the existing cancellation row path.
    """
    db_service, session_id = initialized_db

    listener_id = await executor.register_listener(make_listener_registration())

    queue_record(executor, listener_id, session_id, status="cancelled")
    await execution_pipeline.drain_and_persist(executor)

    # dup-ignore-start: shares the "fetch one row, assert count then fields" shape with
    # tests/unit/core/test_telemetry_repository_schema.py's persist_execution_batch() assertions —
    # different test tier (integration vs. unit) exercising unrelated code paths
    # (execution_pipeline.drain_and_persist here vs. TelemetryRepository.persist_execution_batch
    # there); not extractable across that boundary.
    cursor = await db_service.db.execute(
        "SELECT status FROM executions WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "cancelled"
    # dup-ignore-end


@pytest.mark.parametrize(
    ("exc", "expect_traceback"),
    [
        pytest.param(DependencyError("missing dep"), False, id="dependency_error"),
        pytest.param(HassetteError("framework error"), False, id="hassette_error"),
        pytest.param(ValueError("oops"), True, id="unexpected_error"),
    ],
)
async def test_handler_error_swallowed(executor: CommandExecutor, exc: Exception, expect_traceback: bool) -> None:
    """Handler errors are swallowed (not re-raised) and recorded with status='error'.

    Framework errors are logged via logger.error, so they carry no traceback; an unexpected
    exception goes through logger.exception and stores one.
    """
    listener = make_mock_listener(invoke_side_effect=exc)

    # Should not raise
    await executor.execute(invoke_cmd(listener))

    record = pop_execution_record(executor)
    assert record.status == "error"
    assert record.error_type == type(exc).__name__
    assert record.error_message == str(exc)
    if expect_traceback:
        assert record.error_traceback is not None
        assert type(exc).__name__ in record.error_traceback
    else:
        assert record.error_traceback is None


async def test_success_record_queued(executor: CommandExecutor) -> None:
    """Successful invocation must queue a 'success' record."""
    await executor.execute(invoke_cmd(make_mock_listener()))

    record = pop_execution_record(executor)
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

    await executor.execute(invoke_cmd(listener, effective_timeout=0.05))

    assert pop_execution_record(executor).status == "timed_out"


async def test_execute_timeout_none_is_noop(executor: CommandExecutor) -> None:
    """effective_timeout=None does not enforce timeout."""
    await executor.execute(invoke_cmd(make_mock_listener()))

    assert pop_execution_record(executor).status == "success"


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
        await executor.execute(invoke_cmd(listener, effective_timeout=0.01))

    executor.logger.warning = original_warning  # pyright: ignore[reportAttributeAccessIssue]

    # Only one timeout warning should have been logged (rate-limited by listener_id)
    timeout_warnings = [w for w in warnings_logged if "timed out" in w.lower() or "timeout" in w.lower()]
    assert len(timeout_warnings) == 1, f"Expected 1 timeout warning, got {len(timeout_warnings)}: {timeout_warnings}"


async def test_timeout_warning_lazy_eviction(executor: CommandExecutor) -> None:
    """Stale entries are evicted during rate-limit check."""

    async def slow_handler(_event):
        await asyncio.sleep(10)

    listener = make_mock_listener(listener_id=2)
    listener.invoke = slow_handler
    listener.invoker.invoke = slow_handler

    # Manually seed a stale entry (>60s ago)
    executor._timeout_warn_timestamps = {1: time.monotonic() - 120.0}  # pyright: ignore[reportAttributeAccessIssue]

    # Fire a timeout for a different listener_id
    await executor.execute(invoke_cmd(listener, listener_id=2, effective_timeout=0.01))

    # Stale entry for listener_id=1 should have been evicted
    assert 1 not in executor._timeout_warn_timestamps


async def test_serve_drains_queue_to_db(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """Records placed in the write queue appear in executions after drain."""
    db_service, session_id = initialized_db

    # First register a listener to get a valid listener_id FK
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    # Queue a success record directly
    queue_record(executor, listener_id, session_id)

    # Drain without going through serve() loop — call drain_and_persist directly
    await execution_pipeline.drain_and_persist(executor)

    # Verify it landed in DB
    # dup-ignore-start: shares the "fetch one row, assert count then fields" shape with
    # tests/unit/core/test_telemetry_repository_schema.py's persist_execution_batch() assertions —
    # different test tier (integration vs. unit) exercising unrelated code paths
    # (execution_pipeline.drain_and_persist here vs. TelemetryRepository.persist_execution_batch
    # there); not extractable across that boundary.
    cursor = await db_service.db.execute(
        "SELECT status, listener_id, session_id FROM executions WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "success"
    assert rows[0][1] == listener_id
    assert rows[0][2] == session_id
    # dup-ignore-end


async def test_flush_queue_on_shutdown(executor: CommandExecutor, initialized_db: tuple[DatabaseService, int]) -> None:
    """flush_queue() persists remaining records before returning."""
    db_service, session_id = initialized_db

    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    # Put two records in the queue
    for _ in range(2):
        queue_record(executor, listener_id, session_id, duration_ms=5.0)

    await execution_pipeline.flush_queue(executor)

    # Both records should be in DB, queue should be empty
    assert executor._write_queue.empty()

    cursor = await db_service.db.execute(
        "SELECT COUNT(*) FROM executions WHERE listener_id = ?",
        (listener_id,),
    )
    row = await cursor.fetchone()
    assert row[0] == 2


async def test_execute_job_success_record_queued(executor: CommandExecutor) -> None:
    """Successful job execution queues a unified ExecutionRecord with kind='job'."""
    job = make_mock_job()
    callable_mock = AsyncMock(return_value=None)

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42, source_tier="app", effective_timeout=None)
    await executor.execute(cmd)

    record = pop_execution_record(executor)
    assert record.kind == "job"
    assert record.status == "success"
    assert record.job_id == 42
    assert record.duration_ms >= 0


async def test_execute_job_error_swallowed(executor: CommandExecutor) -> None:
    """Job error is swallowed and queues a unified ExecutionRecord with kind='job'."""
    job = make_mock_job()
    callable_mock = AsyncMock(side_effect=RuntimeError("job failed"))

    cmd = ExecuteJob(job=job, callable=callable_mock, job_db_id=42, source_tier="app", effective_timeout=None)
    await executor.execute(cmd)

    record = pop_execution_record(executor)
    assert record.kind == "job"
    assert record.status == "error"
    assert record.error_type == "RuntimeError"
    assert record.error_message == "job failed"
    assert record.error_traceback is not None


def test_build_record_uses_session_id_directly(db_hassette: AsyncMock) -> None:
    """build_record() reads session_id via try_session_id() and embeds it in the record."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    db_hassette.session_id = 99
    db_hassette.try_session_id.return_value = 99

    cmd = invoke_cmd(make_mock_listener(), listener_id=5)
    result = ExecutionResult()
    result.status = "success"
    result.duration_ms = 1.0

    record = build_execution_record(cmd, result, time.time(), "test-exec-id", session_id=exc.hassette.try_session_id())
    assert isinstance(record, ExecutionRecord)
    assert record.session_id == 99
    assert record.listener_id == 5


async def test_persist_batch_drops_presession_records(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """persist_batch() silently drops records with session_id=None when session unavailable.

    Records queued before _create_session() runs have session_id=None. When the session
    is unavailable at drain time, those records are dropped with a warning.
    """
    db_service, session_id = initialized_db
    reg = make_listener_registration()
    listener_id = await executor.register_listener(reg)

    now = time.time()
    valid = make_execution_record(
        listener_id=listener_id, session_id=session_id, execution_start_ts=now, execution_id=None
    )
    pre_session = make_execution_record(
        listener_id=listener_id, session_id=None, execution_start_ts=now, execution_id=None
    )

    # Patch try_session_id to return None so the "session not ready" path is triggered
    executor.hassette.try_session_id = MagicMock(return_value=None)

    await execution_pipeline.persist_batch(executor, [valid, pre_session])

    # Restore session_id to the real value for the next assertion query
    type(executor.hassette).session_id = PropertyMock(return_value=session_id)
    executor.hassette.try_session_id = MagicMock(return_value=session_id)

    # dup-ignore-start: shares the "fetch one row, assert count then fields" shape with
    # tests/unit/core/test_telemetry_repository_schema.py's persist_execution_batch() assertions —
    # different test tier (integration vs. unit) exercising unrelated code paths
    # (execution_pipeline.drain_and_persist here vs. TelemetryRepository.persist_execution_batch
    # there); not extractable across that boundary.
    cursor = await db_service.db.execute(
        "SELECT session_id FROM executions WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    # valid record has session_id set — it is persisted; pre_session has None — dropped
    assert len(rows) == 1
    assert rows[0][0] == session_id
    # dup-ignore-end


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

    # Create an execution history row
    await db_service.db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db_service.db.commit()

    # Simulate restart: re-register with same natural key (upsert)
    new_id = await executor.register_listener(reg)

    # Must return the SAME ID — FK reference in executions is preserved
    assert new_id == listener_id, (
        f"Re-registration must return the same listener_id={listener_id}, got {new_id}. "
        "FK references from executions would be orphaned if the ID changes."
    )

    # Verify the execution still references the same listener
    # dup-ignore-start: shares the "fetch one row, assert count then fields" shape with
    # tests/unit/core/test_telemetry_repository_schema.py's persist_execution_batch() assertions —
    # different test tier (integration vs. unit) exercising unrelated code paths
    # (execution_pipeline.drain_and_persist here vs. TelemetryRepository.persist_execution_batch
    # there); not extractable across that boundary.
    cursor = await db_service.db.execute(
        "SELECT listener_id FROM executions WHERE listener_id = ?",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == listener_id
    # dup-ignore-end


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
    reg_b = make_listener_registration(
        handler_method="test_app.on_event_b",
        topic="topic.b",
        name="test_app.on_event_b",
    )
    id_a = await executor.register_listener(reg_a)
    id_b = await executor.register_listener(reg_b)

    # Create history for id_b (so it gets retired, not deleted)
    await db_service.db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
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


async def test_reconcile_registrations_forwards_instance_index(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """reconcile_registrations() forwards instance_index through to the repository call.

    Registers a sibling instance's listener and confirms it survives reconciliation scoped
    to a different instance_index — this only passes if CommandExecutor actually forwards
    the kwarg to TelemetryRepository.reconcile_registrations() via DatabaseService.submit(),
    rather than dropping it.
    """
    db_service, _session_id = initialized_db

    id_target = await executor.register_listener(make_listener_registration(instance_index=0))
    id_sibling = await executor.register_listener(
        make_listener_registration(instance_index=1, handler_method="test_app.on_event_sibling")
    )

    # Reconcile only instance_index=0 with no live IDs: id_target should be deleted (stale, no
    # history), id_sibling (a different instance) must be untouched.
    await executor.reconcile_registrations("test_app", [], [], instance_index=0)

    cursor = await db_service.db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (id_target,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0, "Stale listener for the reconciled instance_index should be deleted"

    cursor = await db_service.db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (id_sibling,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1, "Listener for the sibling instance_index should be preserved"
