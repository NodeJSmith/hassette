"""Unit tests for CommandExecutor write-pipeline bounded queue and retry/backoff behavior.

Companion files: ``test_command_executor_pipeline_persist.py`` covers ``build_record`` and
flush/persist behavior; ``test_command_executor_pipeline_serve.py`` covers the ``serve()`` loop,
blocking-event handling, and completion-event warnings. Together these three files replace the
former ``test_command_executor_pipeline.py``.

Tests cover:
- Bounded queue with overflow handling
- RetryableBatch expansion in drain
- Error classification in persist_batch
- FK violation row-by-row fallback
- RetryableBatch.not_before backoff deferral (#656)
"""

import asyncio
import sqlite3
import time
from collections.abc import Callable, Coroutine
from typing import Any

from hassette.core.command_executor import CommandExecutor, RetryableBatch
from hassette.core.execution_record import ExecutionRecord
from hassette.test_utils.factories import make_execution_record

from .conftest import init_executor, make_invocation


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


async def direct_submit(coro: Coroutine[Any, Any, Any]) -> Any:
    """Run a queued database_service.submit() coroutine inline, bypassing the real submit
    queue — the persist_batch() tests below all need this same bypass, differing only in what
    they mock persist_execution_batch to do.
    """
    return await coro


def raising_persist(exc: BaseException) -> Callable[[list[ExecutionRecord]], Coroutine[Any, Any, None]]:
    """Build an async persist_execution_batch stand-in that always raises ``exc``.

    Several persist_batch() error-classification tests below differ only in which exception
    type/message they simulate.
    """

    async def _persist(_recs: list[ExecutionRecord]) -> None:
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
