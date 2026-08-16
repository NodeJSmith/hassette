"""Unit tests for CommandExecutor write-pipeline resilience.

Tests cover:
- Bounded queue with overflow handling
- RetryableBatch expansion in drain and flush
- Error classification in persist_batch
- FK violation row-by-row fallback
- source_tier and is_di_failure in build_record
- flush_queue graceful handling on DB closed
- RetryableBatch.not_before backoff deferral (#656)
- serve() timer-based flush (#657)
"""

import asyncio
import contextlib
import sqlite3
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite

from hassette.commands import InvokeHandler
from hassette.core.block_io_guard import MonkeypatchEvent
from hassette.core.command_executor import CommandExecutor, RetryableBatch
from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.test_utils.factories import make_execution_record
from hassette.types.types import SourceTier

from .test_command_executor import make_result_mock


# Convenience aliases for readability in tests. Delegate to the shared factory but pin
# execution_start_ts/execution_id to this file's original values (wall-clock timestamp,
# unset execution_id) — no test here asserts on either, so this is not a load-bearing
# override, just a faithful behavior-preserving migration off the old local duplicate.
def make_invocation(
    listener_id: int | None = 1,
    session_id: int = 1,
    source_tier: str = "app",
    is_di_failure: bool = False,
) -> ExecutionRecord:
    return make_execution_record(
        kind="handler",
        listener_id=listener_id,
        job_id=None,
        session_id=session_id,
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
        is_di_failure=is_di_failure,
        execution_start_ts=time.time(),
        duration_ms=1.0,
        execution_id=None,
    )


def make_job_record(
    job_id: int | None = 1,
    session_id: int = 1,
    source_tier: str = "app",
) -> ExecutionRecord:
    return make_execution_record(
        kind="job",
        listener_id=None,
        job_id=job_id,
        session_id=session_id,
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
        execution_start_ts=time.time(),
        duration_ms=1.0,
        execution_id=None,
    )


# Real InvokeHandler, unlike the shared make_invoke_handler_cmd() in test_utils/factories.py
# which returns a MagicMock — build_record tests here assert on the constructed object's own
# fields directly.
def make_real_invoke_handler_cmd(*, listener_id: int = 5, source_tier: SourceTier = "app") -> InvokeHandler:
    listener = MagicMock()
    listener.invoker.invoke = AsyncMock()
    event = MagicMock()
    return InvokeHandler(
        listener=listener,
        event=event,
        topic="test/topic",
        listener_id=listener_id,
        source_tier=source_tier,
        effective_timeout=None,
    )


def init_executor(queue_max: int = 10) -> CommandExecutor:
    """Create and minimally init a CommandExecutor for pipeline tests."""
    executor = CommandExecutor.__new__(CommandExecutor)
    executor._write_queue = asyncio.Queue(maxsize=queue_max)
    executor._dropped_overflow = 0
    executor._dropped_exhausted = 0
    executor._dropped_shutdown = 0
    executor._error_handler_failures = 0
    executor._last_capacity_warn_ts = None
    executor._last_unowned_warn_ts = None
    executor._timeout_warn_timestamps = {}
    executor.repository = MagicMock()
    executor.repository.persist_batch = MagicMock()
    executor.hassette = MagicMock()
    executor.hassette.session_id = 42
    executor.hassette.try_session_id.return_value = 42
    executor.hassette.config.database.telemetry_write_queue_max = queue_max
    executor.hassette.config.lifecycle.command_executor_capacity_warn_threshold = 0.75
    executor.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds = 30.0
    executor.hassette.database_service = MagicMock()
    executor.hassette.database_service.submit = AsyncMock(return_value=None)
    executor.logger = MagicMock()
    executor._unique_name = "CommandExecutor.test"
    # Real Event so the module-level mark_ready() (called by serve()) can operate
    # on this bypassed instance.
    executor.ready_event = asyncio.Event()
    executor._ready_reason = None
    return executor


async def direct_submit(coro):
    """Run a queued database_service.submit() coroutine inline, bypassing the real submit
    queue — the persist_batch() tests below all need this same bypass, differing only in what
    they mock persist_execution_batch to do.
    """
    return await coro


def raising_persist(exc: BaseException):
    """Build an async persist_execution_batch stand-in that always raises ``exc``.

    Several persist_batch() error-classification tests below differ only in which exception
    type/message they simulate.
    """

    async def _persist(_recs):
        raise exc

    return _persist


def wire_raising_persist(executor: CommandExecutor, exc: BaseException) -> None:
    """Wire ``executor`` to raise ``exc`` from persist_execution_batch and bypass the submit queue.

    Consolidates the `persist_execution_batch = raising_persist(exc)` +
    `database_service.submit = direct_submit` pairing repeated across the persist_batch()
    error-classification and backoff-delay tests below.
    """
    executor.repository.persist_execution_batch = raising_persist(exc)  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]


async def run_serve_until(executor: CommandExecutor, stopper_coro) -> None:
    """Run executor.serve() alongside a background task that eventually sets shutdown_event,
    then cancel and drain the stopper task cleanly. Shared by the serve() loop tests below,
    which differ only in what the stopper task waits for before signaling shutdown.
    """
    stopper = asyncio.create_task(stopper_coro)
    await executor.serve()
    stopper.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stopper


def make_executor_with_send_event(queue_max: int = 10) -> CommandExecutor:
    """CommandExecutor with hassette.send_event mocked, for emit_completion_events tests."""
    executor = init_executor(queue_max=queue_max)
    executor.hassette.send_event = AsyncMock()
    return executor


async def test_bounded_queue_drops_on_full():
    """Filling a queue beyond maxsize triggers QueueFull; _dropped_overflow is incremented."""
    executor = init_executor(queue_max=3)

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


async def test_enqueue_record_warns_at_configured_capacity_threshold() -> None:
    """enqueue_record logs a capacity WARNING once occupancy *before* the enqueue reaches the
    configured threshold, using lifecycle.command_executor_capacity_warn_threshold (#1041).
    """
    executor = init_executor(queue_max=4)
    executor.hassette.config.lifecycle.command_executor_capacity_warn_threshold = 0.5  # 2/4

    rec = make_invocation()
    executor.enqueue_record(rec)  # current_size=0 before put — below threshold
    assert executor.logger.warning.call_count == 0

    executor.enqueue_record(rec)  # current_size=1 before put — still below threshold
    assert executor.logger.warning.call_count == 0

    executor.enqueue_record(rec)  # current_size=2 before put — at threshold
    assert executor.logger.warning.call_count == 1


async def test_enqueue_record_capacity_warning_respects_configured_rate_limit() -> None:
    """A second enqueue past the threshold is suppressed until the configured rate-limit window
    elapses (#1041).
    """
    executor = init_executor(queue_max=2)
    executor.hassette.config.lifecycle.command_executor_capacity_warn_threshold = 0.5  # 1/2
    executor.hassette.config.lifecycle.command_executor_capacity_warn_rate_limit_seconds = 1000.0

    rec = make_invocation()
    executor.enqueue_record(rec)  # current_size=0 before put — below threshold
    assert executor.logger.warning.call_count == 0

    executor.enqueue_record(rec)  # current_size=1 before put — at threshold, fires
    assert executor.logger.warning.call_count == 1

    executor.enqueue_record(rec)  # current_size=2 before put — still at/above threshold
    assert executor.logger.warning.call_count == 1, "second warning should be suppressed by rate-limit"


async def test_retryable_batch_expanded_in_drain():
    """RetryableBatch enqueued in write_queue expands into the current batch on drain."""
    executor = init_executor()

    inv = make_invocation(listener_id=5)
    job = make_job_record(job_id=7)
    batch = RetryableBatch(records=[inv, job], retry_count=1)

    executor._write_queue.put_nowait(batch)

    captured_records: list[ExecutionRecord] = []
    captured_retry_counts: list[int] = []

    async def fake_persist(records, *, retry_count=0):
        captured_records.extend(records)
        captured_retry_counts.append(retry_count)

    executor.persist_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    await executor.drain_and_persist()

    assert inv in captured_records
    assert job in captured_records
    # RetryableBatch should preserve its retry_count (was 1)
    assert 1 in captured_retry_counts


async def test_id_none_records_persist():
    """Records with listener_id=None (pre-registration orphans) are NOT dropped."""
    executor = init_executor()

    none_inv = make_invocation(listener_id=None, session_id=1)
    records = [none_inv]

    persist_calls: list[list[ExecutionRecord]] = []

    async def fake_persist_batch(recs):
        persist_calls.append(list(recs))

    executor.repository.persist_execution_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor.persist_batch(executor, records)  # pyright: ignore[reportArgumentType]

    # Should have attempted to persist
    assert len(persist_calls) == 1
    assert none_inv in persist_calls[0]


async def test_operational_error_triggers_retry():
    """OperationalError from persist_execution_batch causes re-enqueue as RetryableBatch."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    records = [inv]

    wire_raising_persist(executor, sqlite3.OperationalError("disk I/O error"))

    await CommandExecutor.persist_batch(executor, records)  # pyright: ignore[reportArgumentType]

    # Should have re-enqueued as RetryableBatch
    assert not executor._write_queue.empty()
    queued = executor._write_queue.get_nowait()
    assert isinstance(queued, RetryableBatch)
    assert queued.retry_count == 1
    assert inv in queued.records


async def test_max_retries_drops_batch():
    """RetryableBatch with retry_count=3 is dropped and _dropped_exhausted is incremented."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    exhausted_batch = RetryableBatch(records=[inv], retry_count=3)

    wire_raising_persist(executor, sqlite3.OperationalError("disk I/O error"))

    # Pass retry_count=3 to indicate exhausted batch
    await CommandExecutor.persist_batch(  # pyright: ignore[reportArgumentType]
        executor, exhausted_batch.records, retry_count=3
    )

    # Should NOT have re-enqueued (retry_count >= 3)
    assert executor._write_queue.empty()
    # Should have incremented dropped_exhausted
    assert executor._dropped_exhausted == 1


async def test_data_error_drops_immediately():
    """DataError from persist_execution_batch → drop immediately + REGRESSION log, no re-enqueue."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)

    wire_raising_persist(executor, sqlite3.DataError("column mismatch"))

    await CommandExecutor.persist_batch(executor, [inv])  # pyright: ignore[reportArgumentType]

    # No re-enqueue
    assert executor._write_queue.empty()

    # REGRESSION log
    error_calls = [str(c) for c in executor.logger.error.call_args_list]
    assert any("REGRESSION" in c or "DataError" in c or "non-retryable" in c.lower() for c in error_calls)


async def test_integrity_error_row_by_row_fallback():
    """IntegrityError triggers FK fallback via persist_execution_batch_with_fk_fallback; dropped count tracked."""
    executor = init_executor()

    inv_good = make_invocation(listener_id=1, session_id=1)
    inv_bad = make_invocation(listener_id=999, session_id=1)  # FK violation
    records = [inv_good, inv_bad]

    # Simulate: batch call raises IntegrityError; FK fallback returns 1 dropped record
    async def fake_persist_batch(recs):
        if len(recs) > 1:
            raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")

    async def fake_fk_fallback(_recs):
        return 1  # 1 record dropped

    executor.repository.persist_execution_batch = fake_persist_batch  # pyright: ignore[reportAttributeAccessIssue]
    executor.repository.persist_execution_batch_with_fk_fallback = fake_fk_fallback  # pyright: ignore[reportAttributeAccessIssue]

    executor.hassette.database_service.submit = direct_submit  # pyright: ignore[reportAttributeAccessIssue]

    await CommandExecutor.persist_batch(executor, records)  # pyright: ignore[reportArgumentType]

    # Should have incremented dropped_exhausted for the 1 record that failed even with null FK
    assert executor._dropped_exhausted == 1


def test_build_record_reads_source_tier():
    """build_record sets source_tier from cmd.source_tier and returns ExecutionRecord."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=5, source_tier="framework")
    result = make_result_mock()

    record = CommandExecutor.build_record(executor, cmd, result, time.time(), "test-exec-id")  # pyright: ignore[reportArgumentType]

    assert isinstance(record, ExecutionRecord)
    assert record.kind == "handler"
    assert record.source_tier == "framework"
    assert record.listener_id == 5


def test_build_record_reads_is_di_failure():
    """build_record sets is_di_failure from result.is_di_failure."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=5, source_tier="app")
    result = make_result_mock(
        status="error", error_type="DependencyError", error_message="dep failed", is_di_failure=True
    )

    record = CommandExecutor.build_record(executor, cmd, result, time.time(), "test-exec-id")  # pyright: ignore[reportArgumentType]

    assert isinstance(record, ExecutionRecord)
    assert record.is_di_failure is True


def test_build_record_reads_thread_leaked():
    """build_record copies thread_leaked from result to ExecutionRecord."""
    executor = init_executor()

    cmd = make_real_invoke_handler_cmd(listener_id=1, source_tier="app")

    result = make_result_mock(status="timed_out", thread_leaked=True)

    record = CommandExecutor.build_record(executor, cmd, result, time.time(), "exec-id")  # pyright: ignore[reportArgumentType]
    assert record.thread_leaked is True

    result.thread_leaked = False
    record = CommandExecutor.build_record(executor, cmd, result, time.time(), "exec-id-2")  # pyright: ignore[reportArgumentType]
    assert record.thread_leaked is False


async def test_flush_queue_handles_db_closed():
    """flush_queue does not raise when DB submit raises RuntimeError (DB closed at shutdown)."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    executor._write_queue.put_nowait(inv)

    # Make submit raise RuntimeError (simulating closed DB) — close the coro to avoid leak
    async def fail_submit(coro):
        coro.close()  # prevent "coroutine was never awaited" warning
        raise RuntimeError("database is closed")

    executor.hassette.database_service.submit = fail_submit  # pyright: ignore[reportAttributeAccessIssue]

    async def fake_persist(_recs):
        pass

    executor.repository.persist_execution_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    # flush_queue must NOT raise — shutdown must complete
    await executor.flush_queue()

    # Should have logged something (error/warning about dropped records)
    assert executor.logger.error.called or executor.logger.warning.called


async def test_persist_execution_batch_includes_source_tier():
    """TelemetryRepository.persist_execution_batch INSERT includes source_tier column."""
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
    error_traceback TEXT
);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER,
    job_id                INTEGER,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    execution_id          TEXT UNIQUE,
    trigger_context_id    TEXT,
    trigger_origin        TEXT,
    trigger_mode          TEXT,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt_number        INTEGER NOT NULL DEFAULT 1,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    thread_leaked         INTEGER NOT NULL DEFAULT 0
);
"""

    async with aiosqlite.connect(":memory:") as db:
        db.row_factory = aiosqlite.Row
        await db.executescript(schema)
        await db.commit()

        # Insert a session so FK reference works
        await db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, ?)",
            (time.time(), time.time(), "running"),
        )
        await db.commit()

        mock_db_service = MagicMock()
        mock_db_service.db = db
        repo = TelemetryRepository(mock_db_service)

        record = ExecutionRecord(
            kind="handler",
            listener_id=None,
            session_id=1,
            execution_start_ts=time.time(),
            duration_ms=1.0,
            status="success",
            source_tier="framework",
            is_di_failure=False,
        )

        await repo.persist_execution_batch([record])

        cursor = await db.execute("SELECT source_tier, is_di_failure FROM executions WHERE id = 1")
        row = await cursor.fetchone()
        assert row is not None
        assert row["source_tier"] == "framework"
        assert row["is_di_failure"] == 0


async def test_retryable_batch_future_not_before_is_requeued():
    """A RetryableBatch whose not_before is in the future must be re-enqueued, not persisted."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    batch = RetryableBatch(
        records=[inv],
        retry_count=1,
        not_before=time.monotonic() + 9999.0,
    )
    executor._write_queue.put_nowait(batch)

    persist_called = False

    async def fake_persist(_invs, _jobs, **_kwargs):
        nonlocal persist_called
        persist_called = True

    executor.persist_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    await executor.drain_and_persist()

    # Must NOT have been persisted
    assert not persist_called
    # Must have been put back into the queue
    assert not executor._write_queue.empty()
    requeued = executor._write_queue.get_nowait()
    assert isinstance(requeued, RetryableBatch)
    assert requeued is batch


async def test_retryable_batch_past_not_before_is_persisted():
    """A RetryableBatch whose not_before is in the past (or zero) is persisted normally."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)
    batch = RetryableBatch(
        records=[inv],
        retry_count=1,
        not_before=time.monotonic() - 1.0,  # already elapsed
    )
    executor._write_queue.put_nowait(batch)

    persist_args: list[tuple[list[ExecutionRecord], int]] = []

    async def fake_persist(records, *, retry_count=0):
        persist_args.append((list(records), retry_count))

    executor.persist_batch = fake_persist  # pyright: ignore[reportAttributeAccessIssue]

    await executor.drain_and_persist()

    assert len(persist_args) == 1
    persisted_records, persisted_retry = persist_args[0]
    assert inv in persisted_records
    assert persisted_retry == 1
    assert executor._write_queue.empty()


async def test_retryable_batch_not_before_set_to_backoff_delay():
    """When persist_batch re-enqueues a batch, not_before is set to monotonic + (retry_count + 1)."""
    executor = init_executor()

    inv = make_invocation(listener_id=5, session_id=1)

    wire_raising_persist(executor, sqlite3.OperationalError("disk I/O error"))

    before = time.monotonic()
    # retry_count=0 → backoff should be 1s (retry_count + 1 = 1)
    await CommandExecutor.persist_batch(executor, [inv], retry_count=0)  # pyright: ignore[reportArgumentType]
    after = time.monotonic()

    assert not executor._write_queue.empty()
    queued = executor._write_queue.get_nowait()
    assert isinstance(queued, RetryableBatch)
    assert queued.retry_count == 1
    # not_before should be approximately before + 1s (retry_count + 1 = 0 + 1)
    assert queued.not_before >= before + 1.0
    assert queued.not_before <= after + 2.0


async def test_retryable_batch_backoff_increases_with_retry_count():
    """Backoff grows linearly: retry 0→1s, retry 1→2s, retry 2→3s."""
    for initial_retry in range(3):
        executor = init_executor()
        inv = make_invocation(listener_id=5, session_id=1)

        wire_raising_persist(executor, sqlite3.OperationalError("disk I/O error"))

        before = time.monotonic()
        await CommandExecutor.persist_batch(executor, [inv], retry_count=initial_retry)  # pyright: ignore[reportArgumentType]
        after = time.monotonic()

        queued = executor._write_queue.get_nowait()
        expected_delay = float(initial_retry + 1)
        assert queued.not_before >= before + expected_delay
        assert queued.not_before <= after + expected_delay + 0.1


async def test_serve_loops_without_blocking_when_queue_empty():
    """serve() does not block indefinitely when the queue is empty — the timer causes it to loop."""
    # dup-ignore-start: executor + recorder-stub setup (drain_calls list + fake_drain callback)
    # repeated across the serve() loop tests below. test_serve_timer_drains_items_added_during_drain
    # needs bespoke re-enqueue logic inside its callback, so a shared factory would still need
    # an escape hatch for that one case — not worth the indirection to save these lines twice.
    executor = init_executor()

    # Queue stays empty; the timer should fire and allow the loop to continue (and eventually shut down)
    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 0.05  # very short — timer fires quickly

    # Shut down after two timer cycles; if max_flush_interval_seconds is honoured the whole
    # serve() call completes in well under 1s.  If it were ignored (infinite wait),
    # the test would hang until pytest's overall timeout killed it.
    async def stop_after_two_cycles():
        await asyncio.sleep(0.15)
        shutdown_event.set()

    await run_serve_until(executor, stop_after_two_cycles())

    # No drains expected (queue was empty), but serve() must have returned in time
    assert not drain_calls


async def test_serve_timer_drains_items_added_during_drain():
    """Items put back into the queue during drain_and_persist (e.g. deferred retries) are
    picked up on the next loop iteration, not lost.
    """
    # dup-ignore-start: executor + recorder-stub setup — see the matching comment in
    # test_serve_loops_without_blocking_when_queue_empty above. This occurrence needs its own
    # bespoke re-enqueue branch inside fake_drain, which is exactly why a shared factory isn't
    # worth it across all three serve() loop tests.
    executor = init_executor()

    # First item to seed the initial drain
    inv1 = make_invocation(listener_id=1, session_id=1)
    inv2 = make_invocation(listener_id=2, session_id=1)
    executor._write_queue.put_nowait(inv1)

    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")
        if len(drain_calls) == 1:
            # Simulate a deferred retry being re-enqueued during the first drain
            executor._write_queue.put_nowait(inv2)

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 5.0  # long — rely on item arrival, not timer

    async def stop_after_two_drains():
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(drain_calls) >= 2:
                break
        shutdown_event.set()

    await run_serve_until(executor, stop_after_two_drains())

    # Both drains should have been item-triggered (the re-enqueued item is picked up by queue.get)
    assert len(drain_calls) >= 2
    assert all(d == "item" for d in drain_calls)


async def test_serve_item_flush_drains_queue_on_arrival():
    """serve() drains via first_item path when a queue item arrives before timeout."""
    # dup-ignore-start: executor + recorder-stub setup — see the matching comment in
    # test_serve_loops_without_blocking_when_queue_empty above.
    executor = init_executor()

    drain_calls: list[str] = []

    async def fake_drain(first_item=None):
        drain_calls.append("timer" if first_item is None else "item")

    # dup-ignore-end

    shutdown_event = asyncio.Event()
    executor.shutdown_event = shutdown_event  # pyright: ignore[reportAttributeAccessIssue]

    executor.drain_and_persist = fake_drain  # pyright: ignore[reportAttributeAccessIssue]
    executor.flush_queue = AsyncMock()  # pyright: ignore[reportAttributeAccessIssue]
    executor.hassette.config.database.max_flush_interval_seconds = 5.0  # long interval — item should arrive first

    async def enqueue_then_stop():
        await asyncio.sleep(0.01)
        executor._write_queue.put_nowait(make_invocation(listener_id=1, session_id=1))
        # wait for drain, then shut down
        for _ in range(100):
            await asyncio.sleep(0.01)
            if drain_calls:
                break
        shutdown_event.set()

    await run_serve_until(executor, enqueue_then_stop())

    assert "item" in drain_calls


def test_record_blocking_event_swallows_uninitialized_db() -> None:
    """record_blocking_event is fire-and-forget: a not-yet-initialized database_service
    (``enqueue`` raises ``RuntimeError`` before ``on_initialize``) drops the row and never propagates.

    Regression: the Tier 2 monkeypatch guard wraps ``socket.send``. When it fired while the
    DatabaseService queue was still ``None`` (early startup, shutdown, or the test harness's own
    xdist/rerunfailures socket IPC), the raised ``RuntimeError`` escaped through ``_detect`` into the
    wrapped primitive and crashed the whole caller (pytest INTERNALERROR on 3.11).
    """
    executor = init_executor()
    # Repository returns an opaque handle; the real coroutine is closed by enqueue() in production.
    executor.repository.insert_blocking_event = MagicMock(return_value=MagicMock())
    executor.hassette.database_service.enqueue = MagicMock(
        side_effect=RuntimeError("DatabaseService.enqueue() called before on_initialize()")
    )

    event = MonkeypatchEvent(
        primitive="socket.send",
        source_location="app.py:10",
        app_key="test_app",
        instance_name="default",
        instance_index=0,
        execution_id="01abc",
        tier="monkeypatch",
        detected_at=time.time(),
        reason="attributed",
    )

    # Must not raise — the observational guard path cannot crash the wrapped primitive.
    CommandExecutor.record_blocking_event(executor, event)

    executor.hassette.database_service.enqueue.assert_called_once()


async def test_emit_completion_events_no_warning_for_owned_records() -> None:
    """Normal app-tier records with a populated app_key never trigger the empty-app_key warning."""
    executor = make_executor_with_send_event()

    owned = make_execution_record(app_key="my_app", source_tier="app")
    await CommandExecutor.emit_completion_events(executor, [owned])

    assert executor._last_unowned_warn_ts is None
    executor.hassette.send_event.assert_awaited_once()


async def test_emit_completion_events_no_warning_for_framework_tier_empty_app_key() -> None:
    """Framework-tier records legitimately carry an empty app_key — not the starvation window
    this warning guards against, so it must not fire.
    """
    executor = make_executor_with_send_event()

    framework_record = make_execution_record(app_key="", source_tier="framework")
    await CommandExecutor.emit_completion_events(executor, [framework_record])

    assert executor._last_unowned_warn_ts is None


async def test_emit_completion_events_warns_on_empty_app_key() -> None:
    """An app-tier record with empty app_key (registration meta-miss, e.g. an app reload
    racing the completion event) logs a WARNING.
    """
    executor = make_executor_with_send_event()

    unowned = make_execution_record(app_key="", source_tier="app")
    with patch("hassette.core.command_executor.time.monotonic", return_value=1.0):
        await CommandExecutor.emit_completion_events(executor, [unowned])

    assert executor._last_unowned_warn_ts == 1.0


async def test_emit_completion_events_unowned_warning_rate_limited() -> None:
    """Repeated empty-app_key batches within the suppression window log only once."""
    executor = make_executor_with_send_event()
    unowned = make_execution_record(app_key="", source_tier="app")

    with patch("hassette.core.command_executor.time.monotonic", side_effect=[100.0, 101.0, 102.0]):
        await CommandExecutor.emit_completion_events(executor, [unowned])
        await CommandExecutor.emit_completion_events(executor, [unowned])  # suppressed
        await CommandExecutor.emit_completion_events(executor, [unowned])  # still suppressed

    assert executor._last_unowned_warn_ts == 100.0


async def test_emit_completion_events_unowned_warning_fires_after_rate_limit_window() -> None:
    """A second empty-app_key batch after the suppression window elapses logs again."""
    executor = make_executor_with_send_event()
    unowned = make_execution_record(app_key="", source_tier="app")

    with patch("hassette.core.command_executor.time.monotonic", side_effect=[100.0, 129.999, 130.0]):
        await CommandExecutor.emit_completion_events(executor, [unowned])
        assert executor._last_unowned_warn_ts == 100.0

        await CommandExecutor.emit_completion_events(executor, [unowned])
        assert executor._last_unowned_warn_ts == 100.0

        await CommandExecutor.emit_completion_events(executor, [unowned])

    assert executor._last_unowned_warn_ts == 130.0
