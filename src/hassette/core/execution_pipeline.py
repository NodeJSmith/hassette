"""Batch drain/retry/persist pipeline for CommandExecutor's telemetry write queue.

Every function here takes ``executor: "CommandExecutor"`` as an explicit first argument and
operates on its state (``_write_queue``, ``_dropped_*`` counters, ``_clock``, etc.). Internal
calls among these functions — and from ``CommandExecutor.serve()``/``_execute()`` into them —
are plain module-level calls (e.g. ``persist_batch(executor, ...)``); there is no corresponding
``CommandExecutor.persist_batch`` method. Tests that need to observe a substitute implementation
patch the module attribute directly (e.g. ``monkeypatch.setattr(execution_pipeline,
"persist_batch", fake_persist)``) — Python resolves an unqualified call inside this module
through this module's own globals on every call, so the patched attribute is what every caller
here observes.
"""

import asyncio
import sqlite3
import time
import typing
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace

from hassette.core.execution_record import ExecutionRecord
from hassette.events.hassette import HassetteExecutionCompletedEvent

if typing.TYPE_CHECKING:
    from hassette.core.command_executor import CommandExecutor

_MAX_RETRY_COUNT = 3
_UNOWNED_WARN_RATE_LIMIT_SECS = 30.0
_BATCH_DRAIN_CAP = 100
_RETRY_BACKOFF_BASE_SECONDS = 1.0


@dataclass
class RetryableBatch:
    """A batch of records that failed to persist and should be retried.

    Attributes:
        records: Unified execution records to retry.
        retry_count: Number of times this whole batch has been retried by the executor.
            Unrelated to ``ExecutionRecord.retry_count`` (a per-row schema column that is
            currently always 0); this one drives the in-memory retry/backoff loop.
        not_before: Monotonic timestamp (time.monotonic()) before which this batch
            must not be retried. Zero means eligible immediately.
    """

    records: list[ExecutionRecord] = field(default_factory=list)
    retry_count: int = 0
    not_before: float = 0.0


def enqueue_record(executor: "CommandExecutor", record: ExecutionRecord) -> None:
    """Enqueue a record, dropping and logging if the queue is full.

    Also logs a WARNING when the queue exceeds the configured capacity threshold
    (rate-limited), per lifecycle.command_executor_capacity_warn_threshold /
    lifecycle.command_executor_capacity_warn_rate_limit_seconds.
    """
    max_size = executor._write_queue.maxsize
    current_size = executor._write_queue.qsize()
    lifecycle = executor.hassette.config.lifecycle

    # Capacity warning (rate-limited)
    if max_size > 0 and current_size >= max_size * lifecycle.command_executor_capacity_warn_threshold:
        now = time.monotonic()
        if (
            executor._last_capacity_warn_ts is None
            or now - executor._last_capacity_warn_ts >= lifecycle.command_executor_capacity_warn_rate_limit_seconds
        ):
            executor._last_capacity_warn_ts = now
            executor.logger.warning(
                "Write queue at %d/%d (%.0f%%) — high telemetry load",
                current_size,
                max_size,
                (current_size / max_size) * 100,
            )

    try:
        executor._write_queue.put_nowait(record)
    except asyncio.QueueFull:
        executor._dropped_overflow += 1
        executor.logger.error(
            "Write queue full (%d/%d) — dropping record (total dropped: %d)",
            current_size,
            max_size,
            executor._dropped_overflow,
        )


async def drain_and_persist(
    executor: "CommandExecutor",
    first_item: ExecutionRecord | RetryableBatch | None = None,
) -> None:
    """Drain up to 100 queue items and persist them to DB.

    Separates fresh ExecutionRecord items from RetryableBatch items.
    RetryableBatch items are processed separately to preserve their retry_count.

    Note: the 100-item cap applies to *queue items*, not total records.
    A single RetryableBatch counts as 1 queue item but may contain a full
    prior batch's worth of records. This is acceptable for append-only
    telemetry — a large single transaction at recovery time is benign.

    Args:
        executor: The owning CommandExecutor instance.
        first_item: An already-dequeued item to include as the first record.
            When provided, at most 99 additional items are drained from the queue
            so that the total batch size stays at 100.
    """
    fresh_records: list[ExecutionRecord] = []
    retry_batches: list[RetryableBatch] = []

    def _classify(item: ExecutionRecord | RetryableBatch) -> None:
        if isinstance(item, RetryableBatch):
            retry_batches.append(item)
        elif isinstance(item, ExecutionRecord):
            fresh_records.append(item)
        else:
            typing.assert_never(item)

    if first_item is not None:
        _classify(first_item)

    # Drain remaining items up to a total batch size of _BATCH_DRAIN_CAP (non-blocking)
    for _ in range(_BATCH_DRAIN_CAP - 1 if first_item is not None else _BATCH_DRAIN_CAP):
        try:
            item = executor._write_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        _classify(item)

    # Persist fresh records as a single batch (retry_count=0)
    if fresh_records:
        await persist_batch(executor, fresh_records)

    # Process each RetryableBatch separately to preserve its retry_count.
    # Skip batches whose backoff window has not yet elapsed — re-enqueue them.
    now = time.monotonic()
    for batch in retry_batches:
        if batch.not_before > now:
            # Backoff window still active — put it back for a later drain cycle
            try:
                executor._write_queue.put_nowait(batch)
            except asyncio.QueueFull:
                drop_count = len(batch.records)
                executor._dropped_overflow += drop_count
                executor.logger.error(
                    "Write queue full while deferring retry batch (not_before not reached) "
                    "— dropping %d records (total overflow: %d)",
                    drop_count,
                    executor._dropped_overflow,
                )
            continue
        await persist_batch(executor, batch.records, retry_count=batch.retry_count)


async def flush_queue(executor: "CommandExecutor") -> None:
    """Drain and persist ALL remaining items in the write queue.

    Called during shutdown to ensure no records are lost.
    Unlike drain_and_persist, there is no size limit.

    Wraps persist_batch in try/except — DB may already be closed at shutdown.
    """
    records: list[ExecutionRecord] = []

    while True:
        try:
            item = executor._write_queue.get_nowait()
        except asyncio.QueueEmpty:
            break

        if isinstance(item, RetryableBatch):
            # retry_count and not_before intentionally bypassed — during shutdown,
            # we make a single best-effort persist regardless of backoff state.
            records.extend(item.records)
        elif isinstance(item, ExecutionRecord):
            records.append(item)
        else:
            typing.assert_never(item)

    if not records:
        return

    try:
        await persist_batch(executor, records)
    except Exception:
        drop_count = len(records)
        executor._dropped_shutdown += drop_count
        executor.logger.error(
            "flush_queue: failed to persist %d records during shutdown — dropped (total shutdown: %d)",
            drop_count,
            executor._dropped_shutdown,
        )


async def persist_batch(
    executor: "CommandExecutor",
    records: list[ExecutionRecord],
    *,
    retry_count: int = 0,
) -> None:
    """Write a batch of unified execution records to the DB in a single transaction.

    Session injection:
    - Records with session_id=None are updated to the current session_id at drain time.
    - Records with no session available are dropped with a warning.

    Error classification:
    - sqlite3.OperationalError → retry via RetryableBatch (max 3 retries).
    - sqlite3.IntegrityError → FK violation path (row-by-row fallback).
    - sqlite3.DataError / sqlite3.ProgrammingError → non-retryable, drop + REGRESSION log.
    - Other Exception → non-retryable, drop + ERROR log.

    Args:
        executor: The owning CommandExecutor instance.
        records: Unified execution records to insert into executions.
        retry_count: The number of times this batch has already been retried.
    """
    # Drain-time session_id injection
    # Records enqueued before session creation have session_id=None.
    # Inject the real session_id now at persist time.
    current_session_id = executor.hassette.try_session_id()

    if current_session_id is not None:
        records = [dataclass_replace(r, session_id=current_session_id) if r.session_id is None else r for r in records]
    else:
        # Session still not ready — drop records with None session_id
        no_session = [r for r in records if r.session_id is None]
        if no_session:
            executor.logger.warning(
                "Session not yet created at drain time — dropping %d record(s) with no session_id",
                len(no_session),
            )
        records = [r for r in records if r.session_id is not None]

    if not records:
        return

    try:
        await executor.hassette.database_service.submit(executor.repository.persist_execution_batch(records))
        await emit_completion_events(executor, records)
    except sqlite3.OperationalError as exc:
        # Retryable — transient DB error (disk I/O, locked, etc.)
        if retry_count >= _MAX_RETRY_COUNT:
            drop_count = len(records)
            executor._dropped_exhausted += drop_count
            executor.logger.error(
                "Max retries (%d) exceeded for %d record(s) — dropping (total exhausted: %d): %s",
                _MAX_RETRY_COUNT,
                drop_count,
                executor._dropped_exhausted,
                exc,
            )
        else:
            executor.logger.warning(
                "OperationalError persisting batch — re-enqueueing as RetryableBatch (attempt %d/%d): %s",
                retry_count + 1,
                _MAX_RETRY_COUNT,
                exc,
            )
            try:
                await asyncio.sleep(0)  # yield event loop before retry to avoid starving fresh records
                executor._write_queue.put_nowait(
                    RetryableBatch(
                        records=list(records),
                        retry_count=retry_count + 1,
                        not_before=time.monotonic() + _RETRY_BACKOFF_BASE_SECONDS * (retry_count + 1),
                    )
                )
            except asyncio.QueueFull:
                drop_count = len(records)
                executor._dropped_exhausted += drop_count
                executor.logger.error(
                    "Write queue full while re-enqueueing retry batch — dropping %d records (total exhausted: %d)",
                    drop_count,
                    executor._dropped_exhausted,
                )

    except sqlite3.IntegrityError:
        # FK violation — fall back to row-by-row INSERT
        await handle_fk_violation(executor, records)

    except (sqlite3.DataError, sqlite3.ProgrammingError) as exc:
        # Non-retryable schema/data mismatch — this is a regression
        drop_count = len(records)
        executor.logger.error(
            "REGRESSION: Non-retryable DB error (%s) — dropping %d record(s): %s",
            type(exc).__name__,
            drop_count,
            exc,
        )

    except Exception as exc:
        # Unknown error — drop and log at ERROR
        drop_count = len(records)
        executor.logger.error(
            "Unexpected error persisting %d telemetry record(s) — dropping: %s",
            drop_count,
            exc,
        )


async def handle_fk_violation(
    executor: "CommandExecutor",
    records: list[ExecutionRecord],
) -> None:
    """Handle an IntegrityError by re-inserting records with FK fallback.

    Uses a single database_service.submit() call (one queue slot, one
    transaction) to process all records row-by-row. For each record that
    fails with an IntegrityError, the FK field is nulled and retried.

    Args:
        executor: The owning CommandExecutor instance.
        records: Unified execution records to insert individually.
    """
    try:
        dropped = await executor.hassette.database_service.submit(
            executor.repository.persist_execution_batch_with_fk_fallback(records)
        )
        if dropped > 0:
            executor._dropped_exhausted += dropped
            executor.logger.error(
                "FK violation fallback: %d record(s) dropped even with null FK (total exhausted: %d)",
                dropped,
                executor._dropped_exhausted,
            )
        else:
            await emit_completion_events(executor, records)
    except Exception as exc:
        drop_count = len(records)
        executor._dropped_exhausted += drop_count
        executor.logger.error(
            "FK violation fallback failed entirely — dropping %d record(s) (total exhausted: %d): %s",
            drop_count,
            executor._dropped_exhausted,
            exc,
        )


async def emit_completion_events(
    executor: "CommandExecutor",
    records: list[ExecutionRecord],
) -> None:
    """Emit bus topic events for persisted execution records.

    Fires ``HASSETTE_EVENT_EXECUTION_COMPLETED`` for each app-tier execution
    (both handler and job kinds). The payload's ``kind`` field distinguishes
    handler from job completions.

    Payloads include ``app_key`` and ``instance_index`` sourced directly from the
    in-memory record (populated at build time from the Listener/Job object).

    Errors are suppressed so that emission failures never affect telemetry persistence.
    """
    try:
        app_records = [r for r in records if r.source_tier == "app"]
        # Regression guard: an app-tier completion should always carry an owner.
        # An empty app_key means registration misfired (e.g. an app reload racing
        # the meta lookup). Rate-limited since a sustained storm would otherwise
        # log once per drain tick.
        unowned = sum(1 for r in app_records if not r.app_key)
        if unowned:
            now = executor._clock()
            if (
                executor._last_unowned_warn_ts is None
                or now - executor._last_unowned_warn_ts >= _UNOWNED_WARN_RATE_LIMIT_SECS
            ):
                executor._last_unowned_warn_ts = now
                executor.logger.warning(
                    "Emitting %d app-tier completion event(s) with empty app_key — telemetry will be unattributed",
                    unowned,
                )
        for record in app_records:
            exec_event = HassetteExecutionCompletedEvent.from_record(
                kind=record.kind,
                status=record.status,
                duration_ms=record.duration_ms,
                listener_id=record.listener_id,
                job_id=record.job_id,
                app_key=record.app_key,
                instance_index=record.instance_index,
                error_type=record.error_type,
                thread_leaked=record.thread_leaked,
            )
            await executor.hassette.send_event(exec_event)
    except Exception:
        executor.logger.debug("Failed to emit completion events — ignoring", exc_info=True)
