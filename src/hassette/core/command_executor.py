"""CommandExecutor service: executes handler invocations and scheduled jobs with telemetry."""

import asyncio
import contextlib
import sqlite3
import time
import traceback
import typing
from collections.abc import Awaitable, Callable
from contextvars import Token
from dataclasses import dataclass, field
from dataclasses import replace as dataclass_replace
from typing import ClassVar

import structlog.contextvars
import uuid_utils

from hassette.bus.error_context import BusErrorContext
from hassette.context import CURRENT_EXECUTION_ID
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import SYNTHETIC_ORIGIN, ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.error_context import ErrorContext
from hassette.events.hassette import HassetteExecutionCompletedEvent
from hassette.exceptions import DependencyError, HassetteError
from hassette.resources.base import Resource
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.scheduler.error_context import SchedulerErrorContext
from hassette.types.enums import RestartType
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.execution import ExecutionResult, track_execution

if typing.TYPE_CHECKING:
    from hassette import Hassette

_MAX_RETRY_COUNT = 3
_CAPACITY_WARN_THRESHOLD = 0.75
_CAPACITY_WARN_RATE_LIMIT_SECS = 30.0
_TIMEOUT_WARN_SUPPRESS_SECS = 60.0
_TIMEOUT_WARN_CACHE_MAX = 1000
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


class CommandExecutor(Service):
    """Executes handler invocations and scheduled jobs, persisting execution records to SQLite.

    Lifecycle:
        depends_on: DatabaseService (auto-waited before lifecycle hooks).
        serve(): drains the write queue in batches until shutdown, then flushes remaining records.

    Records are queued immediately after each execution and persisted in batches by serve().
    On shutdown, _flush_queue() persists any remaining records before returning.
    """

    depends_on: ClassVar[list[type[Resource]]] = [DatabaseService]
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=3,
        budget_period_seconds=120,
    )

    _write_queue: asyncio.Queue[ExecutionRecord | RetryableBatch]
    """Bounded queue of execution records pending DB persistence."""

    repository: TelemetryRepository
    """Repository for all telemetry SQL writes."""

    _dropped_overflow: int
    """Count of records dropped because the write queue was full."""

    _dropped_exhausted: int
    """Count of records dropped because retry_count exceeded the maximum."""

    _dropped_shutdown: int
    """Count of records dropped during shutdown flush (DB unavailable)."""

    _error_handler_failures: int
    """Count of user-registered error handler invocations that raised an exception or timed out."""

    _last_capacity_warn_ts: float
    """Monotonic timestamp of the last 75%-capacity warning (rate-limiting)."""

    _timeout_warn_timestamps: dict[int, float]
    """Per-entity timeout warning rate limiter.

    Maps in-memory ID (listener_id or job_id) to the monotonic timestamp of the
    last timeout WARNING. Entries older than 60s are lazily evicted during
    rate-limit checks.
    """

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue(maxsize=hassette.config.database.telemetry_write_queue_max)
        self.repository = TelemetryRepository(hassette.database_service)
        self._dropped_overflow = 0
        self._dropped_exhausted = 0
        self._dropped_shutdown = 0
        self._error_handler_failures = 0
        self._last_capacity_warn_ts = 0.0
        self._timeout_warn_timestamps = {}

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.command_executor

    async def serve(self) -> None:
        """Drain the write queue in batches until shutdown, then flush remaining records.

        Uses asyncio.wait() with a timeout equal to max_flush_interval_seconds so that records
        never sit in the queue longer than that interval, even if the batch size
        threshold is not reached.  When the timeout fires (done is empty), whatever
        is currently in the queue is drained immediately.
        """
        self.mark_ready(reason="CommandExecutor started")
        flush_interval = self.hassette.config.database.max_flush_interval_seconds

        while True:
            get_fut = asyncio.create_task(self._write_queue.get())
            shutdown_fut = asyncio.create_task(self.shutdown_event.wait())

            done, pending = await asyncio.wait(
                [get_fut, shutdown_fut],
                timeout=flush_interval,
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the pending futures to avoid task leaks
            for fut in pending:
                fut.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await fut

            if self.shutdown_event.is_set():
                # get_fut dequeued an item before shutdown was detected — re-enqueue so _flush_queue() picks it up
                if get_fut in done and not get_fut.cancelled() and get_fut.exception() is None:
                    result = get_fut.result()
                    try:
                        self._write_queue.put_nowait(result)
                    except asyncio.QueueFull:
                        self._dropped_overflow += 1
                        self.logger.error(
                            "Write queue full during shutdown — dropping 1 record (total dropped: %d)",
                            self._dropped_overflow,
                        )
                await self._flush_queue()
                return

            if get_fut in done and not get_fut.cancelled() and get_fut.exception() is None:
                # An item arrived — drain the full queue in one batch
                try:
                    await self._drain_and_persist(first_item=get_fut.result())
                except Exception:
                    self.logger.exception(
                        "_drain_and_persist failed — records from this batch are dropped (already dequeued)"
                    )
            elif not done:
                # Timeout — timer fired; drain whatever accumulated without a triggering item
                if not self._write_queue.empty():
                    try:
                        await self._drain_and_persist()
                    except Exception:
                        self.logger.exception(
                            "_drain_and_persist failed (timer flush) — records from this batch may be dropped"
                        )

    def get_drop_counters(self) -> tuple[int, int, int]:
        """Return (dropped_overflow, dropped_exhausted, dropped_shutdown) counters.

        Returns:
            A tuple of counters where:
            - overflow_count: records dropped because the write queue was full.
            - exhausted_count: records dropped because max retries were exceeded.
            - shutdown_count: records dropped during shutdown flush.
        """
        return (self._dropped_overflow, self._dropped_exhausted, self._dropped_shutdown)

    def get_error_handler_failures(self) -> int:
        """Return the count of user error handler invocations that raised or timed out.

        Incremented each time a user-registered error handler (bus or scheduler)
        raises an exception or times out during invocation.

        Returns:
            The cumulative error handler failure count for this session.
        """
        return self._error_handler_failures

    async def execute(self, cmd: InvokeHandler | ExecuteJob) -> None:
        """Execute a command (handler invocation or scheduled job).

        Args:
            cmd: The command to execute.
        """
        match cmd:
            case InvokeHandler():
                await self._execute_handler(cmd)
            case ExecuteJob():
                await self._execute_job(cmd)

    async def _execute(
        self,
        fn: Callable[[], Awaitable[None]],
        cmd: InvokeHandler | ExecuteJob,
        log_error: Callable[[ExecutionResult], None],
        execution_id: str,
    ) -> ExecutionResult:
        """Core execution wrapper: time the call, capture errors, queue the record.

        Wraps ``track_execution()`` with a tier-aware exception contract:

        - ``CancelledError``   — record queued with status='cancelled', then re-raised.
        - ``TimeoutError``     — record queued with status='timed_out', then swallowed.
                                 Warning logged by ``_log_timeout_rate_limited``; not re-raised.
        - ``DependencyError``  — app tier: no traceback; framework tier: traceback included.
        - ``HassetteError``    — app tier: no traceback; framework tier: traceback included.
        - ``Exception``        — record queued with status='error', traceback included.
        - success              — record queued with status='success'.

        ``result`` is initialized before the ``async with`` block so that a
        ``CancelledError`` raised before ``track_execution()`` yields still has a
        safe default to queue.

        Args:
            fn: The async callable to execute (a zero-argument coroutine factory).
            cmd: The originating command, used to build the record in callers.
            log_error: A callback that logs the error details from the result.
                Called for error paths (not cancelled, not success).
            execution_id: The UUIDv7 string generated by the calling method
                (_execute_handler or _execute_job) for this execution.

        Returns:
            The populated ``ExecutionResult``.
        """
        execution_start_ts = time.time()
        result = ExecutionResult(execution_id=execution_id, status="cancelled")
        match cmd.source_tier:
            case "app":
                known: tuple[type[Exception], ...] = (DependencyError, HassetteError)
            case "framework":
                known = ()
            case _:
                raise AssertionError(f"Unexpected source_tier: {cmd.source_tier!r}")
        try:
            async with track_execution(known_errors=known) as result:
                result.execution_id = execution_id
                async with asyncio.timeout(cmd.effective_timeout):
                    await fn()
        except asyncio.CancelledError:
            self._enqueue_record(self._build_record(cmd, result, execution_start_ts, execution_id))
            raise
        except Exception:  # noqa: S110 — intentional: ExecutionResult is populated and error logged upstream
            pass
        # result is available for both success and error paths
        if result.is_timed_out:
            if cmd.effective_timeout is not None:
                self._log_timeout_rate_limited(cmd, result)
            else:
                self.logger.warning(
                    "Handler raised TimeoutError after %.1fms (no framework timeout configured — "
                    "exception originated from user code)",
                    result.duration_ms,
                )
        if result.is_error:
            log_error(result)
        self._enqueue_record(self._build_record(cmd, result, execution_start_ts, execution_id))
        return result

    def _log_timeout_rate_limited(self, cmd: InvokeHandler | ExecuteJob, result: ExecutionResult) -> None:
        """Log a timeout WARNING, rate-limited per entity (60s suppression window).

        Uses the in-memory ID (``listener_id`` for handlers, object identity for jobs)
        to key the suppression window. Lazily evicts stale entries (>60s old)
        during each check.
        """
        now = time.monotonic()

        # Determine the in-memory ID for rate-limiting
        match cmd:
            case InvokeHandler():
                entity_id = cmd.listener.listener_id
                label = f"listener_id={cmd.listener.listener_id}, topic={cmd.topic}"
            case ExecuteJob():
                entity_id = id(cmd.job)
                label = f"job_db_id={cmd.job_db_id}, name={cmd.job.name}"

        # Lazy eviction of stale entries, then cap to bound memory under sustained unavailability
        stale_ids = [k for k, ts in self._timeout_warn_timestamps.items() if now - ts > _TIMEOUT_WARN_SUPPRESS_SECS]
        for k in stale_ids:
            del self._timeout_warn_timestamps[k]
        if len(self._timeout_warn_timestamps) > _TIMEOUT_WARN_CACHE_MAX:
            self._timeout_warn_timestamps.clear()

        # Rate-limit check
        last_ts = self._timeout_warn_timestamps.get(entity_id)
        if last_ts is not None and now - last_ts < _TIMEOUT_WARN_SUPPRESS_SECS:
            return  # suppressed
        self._timeout_warn_timestamps[entity_id] = now

        self.logger.warning(
            "Execution timed out after %.1fms (%s, timeout=%.1fs)",
            result.duration_ms,
            label,
            cmd.effective_timeout,
        )

    def _enqueue_record(self, record: ExecutionRecord) -> None:
        """Enqueue a record, dropping and logging if the queue is full.

        Also logs a WARNING when the queue exceeds 75% capacity (rate-limited).
        """
        max_size = self._write_queue.maxsize
        current_size = self._write_queue.qsize()

        # 75% capacity warning (rate-limited)
        if max_size > 0 and current_size >= int(max_size * _CAPACITY_WARN_THRESHOLD):
            now = time.monotonic()
            if now - self._last_capacity_warn_ts >= _CAPACITY_WARN_RATE_LIMIT_SECS:
                self._last_capacity_warn_ts = now
                self.logger.warning(
                    "Write queue at %d/%d (%.0f%%) — high telemetry load",
                    current_size,
                    max_size,
                    (current_size / max_size) * 100,
                )

        try:
            self._write_queue.put_nowait(record)
        except asyncio.QueueFull:
            self._dropped_overflow += 1
            self.logger.error(
                "Write queue full (%d/%d) — dropping record (total dropped: %d)",
                current_size,
                max_size,
                self._dropped_overflow,
            )

    def _build_record(
        self,
        cmd: InvokeHandler | ExecuteJob,
        result: ExecutionResult,
        execution_start_ts: float,
        execution_id: str,
    ) -> ExecutionRecord:
        """Build a unified ExecutionRecord from the execution result and command.

        session_id is set to None if the session hasn't been created yet (pre-Phase 1).
        The actual session_id is injected at drain time in _persist_batch.

        Args:
            cmd: The originating command.
            result: The execution result with timing and error info.
            execution_start_ts: Unix timestamp when execution began.
            execution_id: UUIDv7 string for this execution instance.
        """
        try:
            session_id: int | None = self.hassette.session_id
        except RuntimeError:
            session_id = None

        match cmd:
            case InvokeHandler():
                return ExecutionRecord(
                    kind="handler",
                    listener_id=cmd.listener_id,
                    job_id=None,
                    session_id=session_id,
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    app_key=cmd.listener.identity.app_key,
                    instance_index=cmd.listener.identity.instance_index,
                    source_tier=cmd.source_tier,
                    is_di_failure=result.is_di_failure,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                    execution_id=execution_id,
                    trigger_context_id=None if cmd.is_synthetic else cmd.event.payload.event_id,
                    trigger_origin=SYNTHETIC_ORIGIN if cmd.is_synthetic else cmd.event.payload.origin,
                )
            case ExecuteJob():
                return ExecutionRecord(
                    kind="job",
                    listener_id=None,
                    job_id=cmd.job_db_id,
                    session_id=session_id,
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    app_key=cmd.job.app_key,
                    instance_index=cmd.job.instance_index,
                    source_tier=cmd.source_tier,
                    is_di_failure=result.is_di_failure,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                    execution_id=execution_id,
                )

    def _bind_execution_context(self, app_key: str | None, instance_index: int) -> tuple[str, Token[str | None]]:
        """Set CURRENT_EXECUTION_ID and bind structlog context vars for the duration of an execution."""
        execution_id = str(uuid_utils.uuid7())
        token = CURRENT_EXECUTION_ID.set(execution_id)
        instance_name: str | None = None
        if app_key:
            app_inst = self.hassette.app_handler.get(app_key, instance_index)
            if app_inst is not None:
                instance_name = app_inst.app_config.instance_name
        structlog.contextvars.bind_contextvars(
            app_key=app_key or None,
            instance_name=instance_name,
            instance_index=instance_index,
        )
        return execution_id, token

    @staticmethod
    def _unbind_execution_context(token: Token[str | None]) -> None:
        CURRENT_EXECUTION_ID.reset(token)
        structlog.contextvars.unbind_contextvars("app_key", "instance_name", "instance_index")

    async def _execute_handler(self, cmd: InvokeHandler) -> None:
        """Execute a listener handler invocation and queue the result record."""
        execution_id, token = self._bind_execution_context(
            cmd.listener.identity.app_key, cmd.listener.identity.instance_index
        )
        try:

            def log_error(result: ExecutionResult) -> None:
                if result.error_traceback is None:
                    self.logger.error(
                        "Handler error (topic=%s, exec=%s): %s", cmd.topic, execution_id, result.error_message
                    )
                else:
                    self.logger.error(
                        "Handler error (topic=%s, handler=%r, exec=%s)\n%s",
                        cmd.topic,
                        cmd.listener,
                        execution_id,
                        result.error_traceback,
                    )

            result = await self._execute(lambda: cmd.listener.invoker.invoke(cmd.event), cmd, log_error, execution_id)

            if (result.is_error or result.is_timed_out) and result.exc is not None:
                error_handler = cmd.listener.invoker.error_handler or cmd.app_level_error_handler
                if error_handler is not None:
                    ctx = BusErrorContext(
                        exception=result.exc,
                        traceback="".join(traceback.format_exception(result.exc)),
                        execution_id=execution_id,
                        topic=cmd.topic,
                        listener_name=repr(cmd.listener),
                        event=cmd.event,
                    )
                    # FIXME(#573): no per-listener rate-limit on error handler spawns — high-frequency
                    # failures can accumulate unbounded concurrent tasks.
                    self.task_bucket.spawn(
                        self._invoke_error_handler(error_handler, ctx),
                        name="executor:bus_error_handler",
                    )
        finally:
            self._unbind_execution_context(token)

    async def _execute_job(self, cmd: ExecuteJob) -> None:
        """Execute a scheduled job and queue the result record."""
        execution_id, token = self._bind_execution_context(cmd.job.app_key, cmd.job.instance_index)
        try:

            def log_error(result: ExecutionResult) -> None:
                if result.error_traceback is None:
                    self.logger.error(
                        "Job error (job_db_id=%s, exec=%s): %s", cmd.job_db_id, execution_id, result.error_message
                    )
                else:
                    self.logger.error(
                        "Job error (job_db_id=%s, exec=%s)\n%s", cmd.job_db_id, execution_id, result.error_traceback
                    )

            result = await self._execute(cmd.callable, cmd, log_error, execution_id)

            if (result.is_error or result.is_timed_out) and result.exc is not None:
                error_handler = cmd.job.error_handler or cmd.app_level_error_handler
                if error_handler is not None:
                    ctx = SchedulerErrorContext(
                        exception=result.exc,
                        traceback="".join(traceback.format_exception(result.exc)),
                        execution_id=execution_id,
                        job_name=cmd.job.name,
                        job_group=cmd.job.group,
                        args=cmd.job.args,
                        kwargs=dict(cmd.job.kwargs),
                    )
                    # FIXME(#573): no per-job rate-limit on error handler spawns.
                    self.task_bucket.spawn(
                        self._invoke_error_handler(error_handler, ctx),
                        name="executor:scheduler_error_handler",
                    )
        finally:
            self._unbind_execution_context(token)

    async def _invoke_error_handler(
        self,
        handler: "Callable",
        ctx: ErrorContext,
    ) -> None:
        """Invoke a user-registered error handler in a separate spawned task.

        Note: CURRENT_EXECUTION_ID is set to the parent execution's ID via inherited
        context snapshot. This is intentional for error correlation but is not reset
        here — sub-tasks spawned by user error handler code will inherit the same ID.
        """
        async_handler = self.task_bucket.make_async_adapter(handler)
        timeout = self.hassette.config.lifecycle.error_handler_timeout_seconds
        label = ctx.log_label
        try:
            async with asyncio.timeout(timeout):
                await async_handler(ctx)
        except TimeoutError:
            self._error_handler_failures += 1
            if timeout is None:
                self.logger.exception("Error handler raised TimeoutError (%s)", label)
            else:
                self.logger.warning("Error handler timed out after %.1fs (%s)", timeout, label)
        except Exception:
            self._error_handler_failures += 1
            self.logger.exception("Error handler raised an exception (%s)", label)

    async def register_listener(self, registration: ListenerRegistration) -> int:
        """Insert a listener registration into the listeners table.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted row.
        """
        listener_id = await self.hassette.database_service.submit(self.repository.register_listener(registration))
        return listener_id

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Insert a scheduled job registration into the scheduled_jobs table.

        Args:
            registration: The scheduled job registration data.

        Returns:
            The row ID of the inserted row.
        """
        job_id = await self.hassette.database_service.submit(self.repository.register_job(registration))
        return job_id

    async def mark_job_cancelled(self, db_id: int) -> None:
        """Set ``cancelled_at`` on the scheduled_jobs row to persist durable cancellation state.

        Delegates to ``TelemetryRepository.mark_job_cancelled`` via ``DatabaseService.submit``.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as cancelled.
        """
        await self.hassette.database_service.submit(self.repository.mark_job_cancelled(db_id))

    async def mark_listener_cancelled(self, db_id: int) -> None:
        """Set ``cancelled_at`` on the listeners row to persist durable cancellation state.

        Delegates to ``TelemetryRepository.mark_listener_cancelled`` via ``DatabaseService.submit``.

        Args:
            db_id: The ``id`` of the ``listeners`` row to mark as cancelled.
        """
        await self.hassette.database_service.submit(self.repository.mark_listener_cancelled(db_id))

    async def reconcile_registrations(
        self,
        app_key: str,
        live_listener_ids: list[int],
        live_job_ids: list[int],
        *,
        session_id: int | None = None,
    ) -> None:
        """Reconcile listener and job registrations for an app after initialization.

        Deletes stale rows without history, sets ``retired_at`` on stale rows with
        history, and deletes ``once=True`` rows from previous sessions. Delegates
        to ``TelemetryRepository.reconcile_registrations`` via ``DatabaseService.submit``.

        Args:
            app_key: The app key to reconcile.
            live_listener_ids: IDs of currently active listener rows.
            live_job_ids: IDs of currently active scheduled_job rows.
            session_id: Current session ID, used to guard once=True row deletion.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        await self.hassette.database_service.submit(
            self.repository.reconcile_registrations(
                app_key,
                live_listener_ids,
                live_job_ids,
                session_id=session_id,
            )
        )

    async def _drain_and_persist(
        self,
        first_item: ExecutionRecord | RetryableBatch | None = None,
    ) -> None:
        """Drain up to 100 queue items and persist them to DB.

        Separates fresh ExecutionRecord items from RetryableBatch items.
        RetryableBatch items are processed separately to preserve their retry_count.

        Note: the 100-item cap applies to *queue items*, not total records.
        A single RetryableBatch counts as 1 queue item but may contain a full
        prior batch's worth of records.  This is acceptable for append-only
        telemetry — a large single transaction at recovery time is benign.

        Args:
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
                item = self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _classify(item)

        # Persist fresh records as a single batch (retry_count=0)
        if fresh_records:
            await self._persist_batch(fresh_records)

        # Process each RetryableBatch separately to preserve its retry_count.
        # Skip batches whose backoff window has not yet elapsed — re-enqueue them.
        now = time.monotonic()
        for batch in retry_batches:
            if batch.not_before > now:
                # Backoff window still active — put it back for a later drain cycle
                try:
                    self._write_queue.put_nowait(batch)
                except asyncio.QueueFull:
                    drop_count = len(batch.records)
                    self._dropped_overflow += drop_count
                    self.logger.error(
                        "Write queue full while deferring retry batch (not_before not reached) "
                        "— dropping %d records (total overflow: %d)",
                        drop_count,
                        self._dropped_overflow,
                    )
                continue
            await self._persist_batch(batch.records, retry_count=batch.retry_count)

    async def _flush_queue(self) -> None:
        """Drain and persist ALL remaining items in the write queue.

        Called during shutdown to ensure no records are lost.
        Unlike _drain_and_persist, there is no size limit.

        Wraps _persist_batch in try/except — DB may already be closed at shutdown.
        """
        records: list[ExecutionRecord] = []

        while True:
            try:
                item = self._write_queue.get_nowait()
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
            await self._persist_batch(records)
        except Exception:
            drop_count = len(records)
            self._dropped_shutdown += drop_count
            self.logger.error(
                "_flush_queue: failed to persist %d records during shutdown — dropped (total shutdown: %d)",
                drop_count,
                self._dropped_shutdown,
            )

    async def _persist_batch(
        self,
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
            records: Unified execution records to insert into executions.
            retry_count: The number of times this batch has already been retried.
        """
        # ---- Drain-time session_id injection ----
        # Records enqueued before session creation have session_id=None.
        # Inject the real session_id now at persist time.
        try:
            current_session_id: int | None = self.hassette.session_id
        except RuntimeError:
            current_session_id = None

        if current_session_id is not None:
            records = [
                dataclass_replace(r, session_id=current_session_id) if r.session_id is None else r for r in records
            ]
        else:
            # Session still not ready — drop records with None session_id
            no_session = [r for r in records if r.session_id is None]
            if no_session:
                self.logger.warning(
                    "Session not yet created at drain time — dropping %d record(s) with no session_id",
                    len(no_session),
                )
            records = [r for r in records if r.session_id is not None]

        if not records:
            return

        try:
            await self.hassette.database_service.submit(self.repository.persist_execution_batch(records))
            await self._emit_completion_events(records)
        except sqlite3.OperationalError as exc:
            # Retryable — transient DB error (disk I/O, locked, etc.)
            if retry_count >= _MAX_RETRY_COUNT:
                drop_count = len(records)
                self._dropped_exhausted += drop_count
                self.logger.error(
                    "Max retries (%d) exceeded for %d record(s) — dropping (total exhausted: %d): %s",
                    _MAX_RETRY_COUNT,
                    drop_count,
                    self._dropped_exhausted,
                    exc,
                )
            else:
                self.logger.warning(
                    "OperationalError persisting batch — re-enqueueing as RetryableBatch (attempt %d/%d): %s",
                    retry_count + 1,
                    _MAX_RETRY_COUNT,
                    exc,
                )
                try:
                    await asyncio.sleep(0)  # yield event loop before retry to avoid starving fresh records
                    self._write_queue.put_nowait(
                        RetryableBatch(
                            records=list(records),
                            retry_count=retry_count + 1,
                            not_before=time.monotonic() + _RETRY_BACKOFF_BASE_SECONDS * (retry_count + 1),
                        )
                    )
                except asyncio.QueueFull:
                    drop_count = len(records)
                    self._dropped_exhausted += drop_count
                    self.logger.error(
                        "Write queue full while re-enqueueing retry batch — dropping %d records (total exhausted: %d)",
                        drop_count,
                        self._dropped_exhausted,
                    )

        except sqlite3.IntegrityError:
            # FK violation — fall back to row-by-row INSERT
            await self._handle_fk_violation(records)

        except (sqlite3.DataError, sqlite3.ProgrammingError) as exc:
            # Non-retryable schema/data mismatch — this is a regression
            drop_count = len(records)
            self.logger.error(
                "REGRESSION: Non-retryable DB error (%s) — dropping %d record(s): %s",
                type(exc).__name__,
                drop_count,
                exc,
            )

        except Exception as exc:
            # Unknown error — drop and log at ERROR
            drop_count = len(records)
            self.logger.error(
                "Unexpected error persisting %d telemetry record(s) — dropping: %s",
                drop_count,
                exc,
            )

    async def _emit_completion_events(
        self,
        records: list[ExecutionRecord],
    ) -> None:
        """Emit bus topic events for persisted execution records.

        Fires ``HASSETTE_EVENT_EXECUTION_COMPLETED`` for each app-tier execution
        (both handler and job kinds). The payload's ``kind`` field distinguishes
        handler from job completions.

        Payloads include ``app_key`` and ``instance_index`` sourced directly from the
        in-memory record (populated at build time from the Listener/ScheduledJob object).

        Errors are suppressed so that emission failures never affect telemetry persistence.
        """
        try:
            app_records = [r for r in records if r.source_tier == "app"]
            # Regression guard: an app-tier completion should always carry an owner.
            # An empty app_key means registration misfired.
            unowned = sum(1 for r in app_records if not r.app_key)
            if unowned:
                self.logger.warning(
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
                )
                await self.hassette.send_event(exec_event)
        except Exception:
            self.logger.debug("Failed to emit completion events — ignoring", exc_info=True)

    async def _handle_fk_violation(
        self,
        records: list[ExecutionRecord],
    ) -> None:
        """Handle an IntegrityError by re-inserting records with FK fallback.

        Uses a single database_service.submit() call (one queue slot, one
        transaction) to process all records row-by-row. For each record that
        fails with an IntegrityError, the FK field is nulled and retried.

        Args:
            records: Unified execution records to insert individually.
        """
        try:
            dropped = await self.hassette.database_service.submit(
                self.repository.persist_execution_batch_with_fk_fallback(records)
            )
            if dropped > 0:
                self._dropped_exhausted += dropped
                self.logger.error(
                    "FK violation fallback: %d record(s) dropped even with null FK (total exhausted: %d)",
                    dropped,
                    self._dropped_exhausted,
                )
            else:
                await self._emit_completion_events(records)
        except Exception as exc:
            drop_count = len(records)
            self._dropped_exhausted += drop_count
            self.logger.error(
                "FK violation fallback failed entirely — dropping %d record(s) (total exhausted: %d): %s",
                drop_count,
                self._dropped_exhausted,
                exc,
            )
