"""CommandExecutor service: executes handler invocations and scheduled jobs with telemetry."""

import asyncio
import contextlib
import dataclasses
import sqlite3
import time
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.exceptions import DependencyError, HassetteError
from hassette.resources.base import Resource, Service
from hassette.scheduler.classes import JobExecutionRecord
from hassette.types.types import LOG_LEVEL_TYPE
from hassette.utils.execution import ExecutionResult, track_execution

if typing.TYPE_CHECKING:
    from hassette import Hassette

_MAX_RETRY_COUNT = 3
_CAPACITY_WARN_THRESHOLD = 0.75
_CAPACITY_WARN_RATE_LIMIT_SECS = 30.0


@dataclass
class RetryableBatch:
    """A batch of records that failed to persist and should be retried.

    Attributes:
        invocations: Handler invocation records to retry.
        job_executions: Job execution records to retry.
        retry_count: Number of times this batch has been retried.
    """

    invocations: list[HandlerInvocationRecord] = field(default_factory=list)
    job_executions: list[JobExecutionRecord] = field(default_factory=list)
    retry_count: int = 0


class CommandExecutor(Service):
    """Executes handler invocations and scheduled jobs, persisting execution records to SQLite.

    Lifecycle:
        on_initialize(): waits for DatabaseService to be ready.
        serve(): drains the write queue in batches until shutdown, then flushes remaining records.

    Records are queued immediately after each execution and persisted in batches by serve().
    On shutdown, _flush_queue() persists any remaining records before returning.
    """

    _write_queue: asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord | RetryableBatch]
    """Bounded queue of execution records pending DB persistence."""

    repository: TelemetryRepository
    """Repository for all telemetry SQL writes."""

    _dropped_overflow: int
    """Count of records dropped because the write queue was full."""

    _dropped_exhausted: int
    """Count of records dropped because retry_count exceeded the maximum."""

    _dropped_no_session: int
    """Count of records dropped because session_id was not yet available at drain time."""

    _dropped_shutdown: int
    """Count of records dropped during shutdown flush (DB unavailable)."""

    _last_capacity_warn_ts: float
    """Monotonic timestamp of the last 75%-capacity warning (rate-limiting)."""

    _timeout_warn_timestamps: dict[int, float]
    """Per-entity timeout warning rate limiter.

    Maps in-memory ID (listener_id or job_id) to the monotonic timestamp of the
    last timeout WARNING. Entries older than 60s are lazily evicted during
    rate-limit checks.
    """

    _TIMEOUT_WARN_SUPPRESS_SECS: float = 60.0
    """Minimum interval between timeout WARNINGs for the same entity."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue(maxsize=hassette.config.telemetry_write_queue_max)
        self.repository = TelemetryRepository(hassette.database_service)
        self._dropped_overflow = 0
        self._dropped_exhausted = 0
        self._dropped_no_session = 0
        self._dropped_shutdown = 0
        self._last_capacity_warn_ts = 0.0
        self._timeout_warn_timestamps = {}

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        """Return the log level from the config for this resource."""
        return self.hassette.config.command_executor_log_level

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_initialize(self) -> None:
        """Wait for DatabaseService to be ready."""
        await self.hassette.wait_for_ready([self.hassette.database_service])

    async def serve(self) -> None:
        """Drain the write queue in batches until shutdown, then flush remaining records."""
        self.mark_ready(reason="CommandExecutor started")

        while True:
            get_fut = asyncio.ensure_future(self._write_queue.get())
            shutdown_fut = asyncio.ensure_future(self.shutdown_event.wait())

            done, pending = await asyncio.wait(
                [get_fut, shutdown_fut],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel the pending future to avoid task leaks
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

            # Queue has an item — drain the full queue in one batch
            if get_fut in done and not get_fut.cancelled() and get_fut.exception() is None:
                try:
                    await self._drain_and_persist(first_item=get_fut.result())
                except Exception:
                    self.logger.exception(
                        "_drain_and_persist failed — records from this batch are dropped (already dequeued)"
                    )

    def get_drop_counters(self) -> tuple[int, int, int, int]:
        """Return (dropped_overflow, dropped_exhausted, dropped_no_session, dropped_shutdown) counters.

        Returns:
            A tuple of counters where:
            - overflow_count: records dropped because the write queue was full.
            - exhausted_count: records dropped because max retries were exceeded.
            - no_session_count: records dropped because session_id was unavailable at drain time.
            - shutdown_count: records dropped during shutdown flush.
        """
        return (self._dropped_overflow, self._dropped_exhausted, self._dropped_no_session, self._dropped_shutdown)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

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
    ) -> ExecutionResult:
        """Core execution wrapper: time the call, capture errors, queue the record.

        Wraps ``track_execution()`` with a tier-aware exception contract:

        - ``CancelledError``   — record queued with status='cancelled', then re-raised.
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

        Returns:
            The populated ``ExecutionResult``.
        """
        execution_start_ts = time.time()
        result = ExecutionResult()  # safe default if CancelledError fires before yield
        match cmd.source_tier:
            case "app":
                known: tuple[type[Exception], ...] = (DependencyError, HassetteError)
            case "framework":
                known = ()
            case _:
                raise AssertionError(f"Unexpected source_tier: {cmd.source_tier!r}")
        try:
            async with track_execution(known_errors=known) as result:
                async with asyncio.timeout(cmd.effective_timeout):
                    await fn()
        except asyncio.CancelledError:
            self._enqueue_record(self._build_record(cmd, result, execution_start_ts))
            raise
        except Exception:
            pass  # track_execution() already re-raised; result is populated. Swallowing is intentional.
        # result is available for both success and error paths
        if result.is_timed_out:
            self._log_timeout_rate_limited(cmd, result)
        if result.is_error:
            log_error(result)
        self._enqueue_record(self._build_record(cmd, result, execution_start_ts))
        return result

    def _log_timeout_rate_limited(self, cmd: InvokeHandler | ExecuteJob, result: ExecutionResult) -> None:
        """Log a timeout WARNING, rate-limited per entity (60s suppression window).

        Uses the in-memory ID (``listener_id`` for handlers, ``job.job_id`` for jobs)
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
                entity_id = cmd.job.job_id
                label = f"job_id={cmd.job.job_id}, job_db_id={cmd.job_db_id}"

        # Lazy eviction of stale entries
        stale_ids = [
            k for k, ts in self._timeout_warn_timestamps.items() if now - ts > self._TIMEOUT_WARN_SUPPRESS_SECS
        ]
        for k in stale_ids:
            del self._timeout_warn_timestamps[k]

        # Rate-limit check
        if entity_id is not None:
            last_ts = self._timeout_warn_timestamps.get(entity_id)
            if last_ts is not None and now - last_ts < self._TIMEOUT_WARN_SUPPRESS_SECS:
                return  # suppressed
            self._timeout_warn_timestamps[entity_id] = now

        self.logger.warning(
            "Execution timed out after %.1fms (%s, timeout=%.1fs)",
            result.duration_ms,
            label,
            cmd.effective_timeout if cmd.effective_timeout is not None else 0.0,
        )

    def _enqueue_record(self, record: HandlerInvocationRecord | JobExecutionRecord) -> None:
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
    ) -> HandlerInvocationRecord | JobExecutionRecord:
        """Build the appropriate record type from the execution result and command.

        session_id is set to None if the session hasn't been created yet (pre-Phase 1).
        The actual session_id is injected at drain time in _persist_batch.
        """
        try:
            session_id: int | None = self.hassette.session_id
        except RuntimeError:
            session_id = None

        match cmd:
            case InvokeHandler():
                return HandlerInvocationRecord(
                    listener_id=cmd.listener_id,
                    session_id=session_id,
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    source_tier=cmd.source_tier,
                    is_di_failure=result.is_di_failure,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                )
            case ExecuteJob():
                return JobExecutionRecord(
                    job_id=cmd.job_db_id,
                    session_id=session_id,
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    source_tier=cmd.source_tier,
                    is_di_failure=result.is_di_failure,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                )

    async def _execute_handler(self, cmd: InvokeHandler) -> None:
        """Execute a listener handler invocation and queue the result record.

        Exception contract (tier-aware — see ``_execute()`` docstring for details).
        """

        def _log_error(result: ExecutionResult) -> None:
            if result.error_traceback is None:
                self.logger.error("Handler error (topic=%s): %s", cmd.topic, result.error_message)
            else:
                self.logger.error(
                    "Handler error (topic=%s, handler=%r)\n%s", cmd.topic, cmd.listener, result.error_traceback
                )

        await self._execute(lambda: cmd.listener.invoke(cmd.event), cmd, _log_error)

    async def _execute_job(self, cmd: ExecuteJob) -> None:
        """Execute a scheduled job and queue the result record.

        Exception contract (tier-aware — see ``_execute()`` docstring for details).
        """

        def _log_error(result: ExecutionResult) -> None:
            if result.error_traceback is None:
                self.logger.error("Job error (job_db_id=%s): %s", cmd.job_db_id, result.error_message)
            else:
                self.logger.error("Job error (job_db_id=%s)\n%s", cmd.job_db_id, result.error_traceback)

        await self._execute(cmd.callable, cmd, _log_error)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_listener(self, registration: ListenerRegistration) -> int:
        """Insert a listener registration into the listeners table.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted row.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        return await self.hassette.database_service.submit(self.repository.register_listener(registration))

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Insert a scheduled job registration into the scheduled_jobs table.

        Args:
            registration: The scheduled job registration data.

        Returns:
            The row ID of the inserted row.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        return await self.hassette.database_service.submit(self.repository.register_job(registration))

    async def mark_job_cancelled(self, db_id: int) -> None:
        """Set ``cancelled_at`` on the scheduled_jobs row to persist durable cancellation state.

        Delegates to ``TelemetryRepository.mark_job_cancelled`` via ``DatabaseService.submit``.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as cancelled.
        """
        await self.hassette.database_service.submit(self.repository.mark_job_cancelled(db_id))

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

    # ------------------------------------------------------------------
    # Queue persistence
    # ------------------------------------------------------------------

    async def _drain_and_persist(
        self,
        first_item: HandlerInvocationRecord | JobExecutionRecord | RetryableBatch | None = None,
    ) -> None:
        """Drain up to 100 queue items and persist them to DB.

        Separates HandlerInvocationRecord and JobExecutionRecord items into
        separate batches, writing each with executemany in a single transaction.
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
        fresh_invocations: list[HandlerInvocationRecord] = []
        fresh_job_executions: list[JobExecutionRecord] = []
        retry_batches: list[RetryableBatch] = []

        def _classify(item: HandlerInvocationRecord | JobExecutionRecord | RetryableBatch) -> None:
            if isinstance(item, RetryableBatch):
                retry_batches.append(item)
            elif isinstance(item, HandlerInvocationRecord):
                fresh_invocations.append(item)
            elif isinstance(item, JobExecutionRecord):
                fresh_job_executions.append(item)
            else:
                typing.assert_never(item)

        if first_item is not None:
            _classify(first_item)

        # Drain remaining items up to a total batch size of 100 (non-blocking)
        for _ in range(99 if first_item is not None else 100):
            try:
                item = self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            _classify(item)

        # Persist fresh records as a single batch (retry_count=0)
        if fresh_invocations or fresh_job_executions:
            await self._persist_batch(fresh_invocations, fresh_job_executions)

        # Process each RetryableBatch separately to preserve its retry_count
        for batch in retry_batches:
            await self._persist_batch(batch.invocations, batch.job_executions, retry_count=batch.retry_count)

    async def _flush_queue(self) -> None:
        """Drain and persist ALL remaining items in the write queue.

        Called during shutdown to ensure no records are lost.
        Unlike _drain_and_persist, there is no size limit.

        Wraps _persist_batch in try/except — DB may already be closed at shutdown.
        """
        invocations: list[HandlerInvocationRecord] = []
        job_executions: list[JobExecutionRecord] = []

        while True:
            try:
                item = self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if isinstance(item, RetryableBatch):
                # retry_count intentionally discarded — during shutdown, we make a
                # single best-effort attempt regardless of prior failure count.
                invocations.extend(item.invocations)
                job_executions.extend(item.job_executions)
            elif isinstance(item, HandlerInvocationRecord):
                invocations.append(item)
            elif isinstance(item, JobExecutionRecord):
                job_executions.append(item)
            else:
                typing.assert_never(item)

        if not invocations and not job_executions:
            return

        try:
            await self._persist_batch(invocations, job_executions)
        except Exception:
            drop_count = len(invocations) + len(job_executions)
            self._dropped_shutdown += drop_count
            self.logger.error(
                "_flush_queue: failed to persist %d records during shutdown — dropped (total shutdown: %d)",
                drop_count,
                self._dropped_shutdown,
            )

    async def _persist_batch(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
        *,
        retry_count: int = 0,
    ) -> None:
        """Write a batch of execution records to the DB in a single transaction.

        Sentinel filtering:
        - listener_id == 0 / job_id == 0 → REGRESSION drop (should never happen after phased startup).
        - listener_id is None / job_id is None → persist normally (pre-registration orphan).
        - session_id == 0 → REGRESSION drop.

        Error classification:
        - sqlite3.OperationalError → retry via RetryableBatch (max 3 retries).
        - sqlite3.IntegrityError → FK violation path (row-by-row fallback).
        - sqlite3.DataError / sqlite3.ProgrammingError → non-retryable, drop + REGRESSION log.
        - Other Exception → non-retryable, drop + ERROR log.

        Args:
            invocations: Handler invocation records to insert into handler_invocations.
            job_executions: Job execution records to insert into job_executions.
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
            invocations = [
                dataclasses.replace(r, session_id=current_session_id) if r.session_id is None else r
                for r in invocations
            ]
            job_executions = [
                dataclasses.replace(r, session_id=current_session_id) if r.session_id is None else r
                for r in job_executions
            ]
        else:
            # Session still not ready — drop records with None session_id
            no_session_invocations = [r for r in invocations if r.session_id is None]
            no_session_jobs = [r for r in job_executions if r.session_id is None]
            if no_session_invocations or no_session_jobs:
                drop_count = len(no_session_invocations) + len(no_session_jobs)
                self._dropped_no_session += drop_count
                self.logger.warning(
                    "Session not yet created at drain time — dropping %d record(s) with no session_id "
                    "(total no_session: %d)",
                    drop_count,
                    self._dropped_no_session,
                )
            invocations = [r for r in invocations if r.session_id is not None]
            job_executions = [r for r in job_executions if r.session_id is not None]

        # ---- Sentinel guard: id == 0 → REGRESSION drop ----
        # session_id == 0 is also a regression sentinel
        bad_invocations = [r for r in invocations if r.listener_id == 0 or r.session_id == 0]
        bad_jobs = [r for r in job_executions if r.job_id == 0 or r.session_id == 0]

        if bad_invocations:
            self.logger.error(
                "REGRESSION: Dropping %d handler invocation record(s) with listener_id=0 or session_id=0 "
                "— this should not happen after phased startup",
                len(bad_invocations),
            )
        if bad_jobs:
            self.logger.error(
                "REGRESSION: Dropping %d job execution record(s) with job_id=0 or session_id=0 "
                "— this should not happen after phased startup",
                len(bad_jobs),
            )

        # Keep only records that are not sentinel-zero (None is allowed)
        invocations = [r for r in invocations if r.listener_id != 0 and r.session_id != 0]
        job_executions = [r for r in job_executions if r.job_id != 0 and r.session_id != 0]

        if not invocations and not job_executions:
            return

        try:
            await self.hassette.database_service.submit(self.repository.persist_batch(invocations, job_executions))
        except sqlite3.OperationalError as exc:
            # Retryable — transient DB error (disk I/O, locked, etc.)
            if retry_count >= _MAX_RETRY_COUNT:
                drop_count = len(invocations) + len(job_executions)
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
                    self._write_queue.put_nowait(
                        RetryableBatch(
                            invocations=list(invocations),
                            job_executions=list(job_executions),
                            retry_count=retry_count + 1,
                        )
                    )
                except asyncio.QueueFull:
                    drop_count = len(invocations) + len(job_executions)
                    self._dropped_exhausted += drop_count
                    self.logger.error(
                        "Write queue full while re-enqueueing retry batch — dropping %d records (total exhausted: %d)",
                        drop_count,
                        self._dropped_exhausted,
                    )

        except sqlite3.IntegrityError:
            # FK violation — fall back to row-by-row INSERT
            await self._handle_fk_violation(invocations, job_executions)

        except (sqlite3.DataError, sqlite3.ProgrammingError) as exc:
            # Non-retryable schema/data mismatch — this is a regression
            drop_count = len(invocations) + len(job_executions)
            self.logger.error(
                "REGRESSION: Non-retryable DB error (%s) — dropping %d record(s): %s",
                type(exc).__name__,
                drop_count,
                exc,
            )

        except Exception as exc:
            # Unknown error — drop and log at ERROR
            drop_count = len(invocations) + len(job_executions)
            self.logger.error(
                "Unexpected error persisting %d telemetry record(s) — dropping: %s",
                drop_count,
                exc,
            )

    async def _handle_fk_violation(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> None:
        """Handle an IntegrityError by re-inserting records with FK fallback.

        Uses a single database_service.submit() call (one queue slot, one
        transaction) to process all records row-by-row. For each record that
        fails with an IntegrityError, the FK field is nulled and retried.

        Args:
            invocations: Handler invocation records to insert individually.
            job_executions: Job execution records to insert individually.
        """
        try:
            dropped = await self.hassette.database_service.submit(
                self.repository.persist_batch_with_fk_fallback(invocations, job_executions)
            )
            if dropped > 0:
                self._dropped_exhausted += dropped
                self.logger.error(
                    "FK violation fallback: %d record(s) dropped even with null FK (total exhausted: %d)",
                    dropped,
                    self._dropped_exhausted,
                )
        except Exception as exc:
            drop_count = len(invocations) + len(job_executions)
            self._dropped_exhausted += drop_count
            self.logger.error(
                "FK violation fallback failed entirely — dropping %d record(s) (total exhausted: %d): %s",
                drop_count,
                self._dropped_exhausted,
                exc,
            )
