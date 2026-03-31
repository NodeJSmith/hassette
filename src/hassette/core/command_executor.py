"""CommandExecutor service: executes handler invocations and scheduled jobs with telemetry."""

import asyncio
import contextlib
import time
import typing
from collections.abc import Awaitable, Callable

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.exceptions import DependencyError, HassetteError
from hassette.resources.base import Resource, Service
from hassette.scheduler.classes import JobExecutionRecord
from hassette.utils.execution import ExecutionResult, track_execution

if typing.TYPE_CHECKING:
    from hassette import Hassette


class CommandExecutor(Service):
    """Executes handler invocations and scheduled jobs, persisting execution records to SQLite.

    Lifecycle:
        on_initialize(): waits for DatabaseService to be ready.
        serve(): drains the write queue in batches until shutdown, then flushes remaining records.

    Records are queued immediately after each execution and persisted in batches by serve().
    On shutdown, _flush_queue() persists any remaining records before returning.
    """

    _write_queue: asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord]
    """Unbounded queue of execution records pending DB persistence."""

    repository: TelemetryRepository
    """Repository for all telemetry SQL writes."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue()
        self.repository = TelemetryRepository(hassette.database_service)

    @property
    def config_log_level(self) -> str:
        """Return the log level from the config for this resource."""
        return self.hassette.config.command_executor_log_level

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def on_initialize(self) -> None:
        """Wait for DatabaseService to be ready."""
        await self.hassette.wait_for_ready([self.hassette.database_service])

    def _safe_session_id(self) -> int:
        """Return the current session ID.

        With phased startup, the session is always created before any service
        can fire a handler. Falls back to 0 on error to avoid crash cascades
        inside exception handlers (the persist layer's regression guard will
        drop and log the record).
        """
        try:
            return self.hassette.session_id
        except RuntimeError:
            self.logger.error("Session ID unavailable — record will be dropped by persist guard")
            return 0

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
                    self._write_queue.put_nowait(result)
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

        Wraps ``track_execution()`` with the full 5-branch exception contract:

        - ``CancelledError``   — record queued with status='cancelled', then re-raised.
        - ``DependencyError``  — record queued with status='error', no traceback.
        - ``HassetteError``    — record queued with status='error', no traceback.
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
        try:
            async with track_execution(known_errors=(DependencyError, HassetteError)) as result:
                await fn()
        except asyncio.CancelledError:
            self._write_queue.put_nowait(self._build_record(cmd, result, execution_start_ts))
            raise
        except Exception:
            pass  # track_execution() already re-raised; result is populated. Swallowing is intentional.
        # result is available for both success and error paths
        if result.is_error:
            log_error(result)
        self._write_queue.put_nowait(self._build_record(cmd, result, execution_start_ts))
        return result

    def _build_record(
        self,
        cmd: InvokeHandler | ExecuteJob,
        result: ExecutionResult,
        execution_start_ts: float,
    ) -> HandlerInvocationRecord | JobExecutionRecord:
        """Build the appropriate record type from the execution result and command."""
        match cmd:
            case InvokeHandler():
                return HandlerInvocationRecord(
                    listener_id=cmd.listener_id,
                    session_id=self._safe_session_id(),
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                )
            case ExecuteJob():
                return JobExecutionRecord(
                    job_id=cmd.job_db_id,
                    session_id=self._safe_session_id(),
                    execution_start_ts=execution_start_ts,
                    duration_ms=result.duration_ms,
                    status=result.status,
                    error_type=result.error_type,
                    error_message=result.error_message,
                    error_traceback=result.error_traceback,
                )

    async def _execute_handler(self, cmd: InvokeHandler) -> None:
        """Execute a listener handler invocation and queue the result record.

        Exception contract:
            CancelledError   → record queued with status='cancelled', then re-raised.
            DependencyError  → record queued with status='error', logger.error (no traceback).
            HassetteError    → record queued with status='error', logger.error (no traceback).
            Exception        → record queued with status='error', logger.error (with traceback string).
            success          → record queued with status='success'.
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

        Exception contract is identical to _execute_handler, but uses JobExecutionRecord.
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

    # ------------------------------------------------------------------
    # Registration cleanup
    # ------------------------------------------------------------------

    async def clear_registrations(self, app_key: str) -> None:
        """Delete all listener and scheduled job registrations for an app.

        Called at start_app() time before re-registration so that stale rows
        from previous sessions (or removed handlers/jobs) are cleaned up.
        History rows (handler_invocations, job_executions) are preserved with
        NULL parent references via ON DELETE SET NULL.

        Args:
            app_key: The app key whose registrations to delete.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        await self.hassette.database_service.submit(self.repository.clear_registrations(app_key))

    # ------------------------------------------------------------------
    # Queue persistence
    # ------------------------------------------------------------------

    async def _drain_and_persist(
        self,
        first_item: HandlerInvocationRecord | JobExecutionRecord | None = None,
    ) -> None:
        """Drain up to 100 items from the write queue and persist them to DB.

        Separates HandlerInvocationRecord and JobExecutionRecord items into
        separate batches, writing each with executemany in a single transaction.

        Args:
            first_item: An already-dequeued item to include as the first record.
                When provided, at most 99 additional items are drained from the queue
                so that the total batch size stays at 100.
        """
        invocations: list[HandlerInvocationRecord] = []
        job_executions: list[JobExecutionRecord] = []

        if first_item is not None:
            if isinstance(first_item, HandlerInvocationRecord):
                invocations.append(first_item)
            else:
                job_executions.append(first_item)

        # Drain remaining items up to a total batch size of 100 (non-blocking)
        for _ in range(99 if first_item is not None else 100):
            try:
                item = self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if isinstance(item, HandlerInvocationRecord):
                invocations.append(item)
            else:
                job_executions.append(item)

        await self._persist_batch(invocations, job_executions)

    async def _flush_queue(self) -> None:
        """Drain and persist ALL remaining items in the write queue.

        Called during shutdown to ensure no records are lost.
        Unlike _drain_and_persist, there is no size limit.
        """
        invocations: list[HandlerInvocationRecord] = []
        job_executions: list[JobExecutionRecord] = []

        while True:
            try:
                item = self._write_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if isinstance(item, HandlerInvocationRecord):
                invocations.append(item)
            else:
                job_executions.append(item)

        await self._persist_batch(invocations, job_executions)

    async def _persist_batch(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> None:
        """Write a batch of execution records to the DB in a single transaction.

        Sentinel filtering (listener_id == 0, session_id == 0) is performed here
        before delegating to the repository. This guard stays in CommandExecutor
        so that the repository remains a pure persistence layer with no policy logic.

        Args:
            invocations: Handler invocation records to insert into handler_invocations.
            job_executions: Job execution records to insert into job_executions.
        """
        # Defense-in-depth: with phased startup and direct dispatch for internal handlers,
        # no code path should produce id=0 sentinel records. If they appear, it's a regression.
        unregistered_invocations = [r for r in invocations if r.listener_id == 0 or r.session_id == 0]
        unregistered_jobs = [r for r in job_executions if r.job_id == 0 or r.session_id == 0]
        if unregistered_invocations:
            self.logger.error(
                "REGRESSION: Dropping %d handler invocation record(s) with listener_id=0 or session_id=0 "
                "— this should not happen after phased startup",
                len(unregistered_invocations),
            )
        if unregistered_jobs:
            self.logger.error(
                "REGRESSION: Dropping %d job execution record(s) with job_id=0 or session_id=0 "
                "— this should not happen after phased startup",
                len(unregistered_jobs),
            )
        invocations = [r for r in invocations if r.listener_id != 0 and r.session_id != 0]
        job_executions = [r for r in job_executions if r.job_id != 0 and r.session_id != 0]

        await self.hassette.database_service.submit(self.repository.persist_batch(invocations, job_executions))
