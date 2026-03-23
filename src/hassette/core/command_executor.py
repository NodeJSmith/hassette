"""CommandExecutor service: executes handler invocations and scheduled jobs with telemetry."""

import asyncio
import contextlib
import time
import traceback
import typing

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.exceptions import DependencyError, HassetteError
from hassette.resources.base import Resource, Service
from hassette.scheduler.classes import JobExecutionRecord

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

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self._write_queue = asyncio.Queue()

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
                await self._drain_and_persist(first_item=get_fut.result())

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

    async def _execute_handler(self, cmd: InvokeHandler) -> None:
        """Execute a listener handler invocation and queue the result record.

        Exception contract:
            CancelledError   → record queued with status='cancelled', then re-raised.
            DependencyError  → record queued with status='error', logger.error (no traceback).
            HassetteError    → record queued with status='error', logger.error (no traceback).
            Exception        → record queued with status='error', logger.exception (with traceback).
            success          → record queued with status='success'.
        """
        execution_start_ts = time.time()
        _mono_start = time.monotonic()

        try:
            await cmd.listener.invoke(cmd.event)
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            record = HandlerInvocationRecord(
                listener_id=cmd.listener_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="cancelled",
                error_type=None,
                error_message=None,
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            raise
        except DependencyError as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.error("Handler DI error (topic=%s): %s", cmd.topic, e)
            record = HandlerInvocationRecord(
                listener_id=cmd.listener_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        except HassetteError as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.error("Handler error (topic=%s): %s", cmd.topic, e)
            record = HandlerInvocationRecord(
                listener_id=cmd.listener_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        except Exception as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.exception("Handler error (topic=%s, handler=%r)", cmd.topic, cmd.listener)
            tb = traceback.format_exc()
            record = HandlerInvocationRecord(
                listener_id=cmd.listener_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=tb,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        else:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            record = HandlerInvocationRecord(
                listener_id=cmd.listener_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="success",
                error_type=None,
                error_message=None,
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)

    async def _execute_job(self, cmd: ExecuteJob) -> None:
        """Execute a scheduled job and queue the result record.

        Exception contract is identical to _execute_handler, but uses JobExecutionRecord.
        """
        execution_start_ts = time.time()
        _mono_start = time.monotonic()

        try:
            await cmd.callable()
        except asyncio.CancelledError:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            record = JobExecutionRecord(
                job_id=cmd.job_db_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="cancelled",
                error_type=None,
                error_message=None,
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            raise
        except DependencyError as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.error("Job DI error (job_db_id=%s): %s", cmd.job_db_id, e)
            record = JobExecutionRecord(
                job_id=cmd.job_db_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        except HassetteError as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.error("Job error (job_db_id=%s): %s", cmd.job_db_id, e)
            record = JobExecutionRecord(
                job_id=cmd.job_db_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        except Exception as e:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            self.logger.exception("Job error (job_db_id=%s)", cmd.job_db_id)
            tb = traceback.format_exc()
            record = JobExecutionRecord(
                job_id=cmd.job_db_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="error",
                error_type=type(e).__name__,
                error_message=str(e),
                error_traceback=tb,
            )
            self._write_queue.put_nowait(record)
            await self._run_error_hooks(e, cmd)
        else:
            duration_ms = (time.monotonic() - _mono_start) * 1000
            record = JobExecutionRecord(
                job_id=cmd.job_db_id,
                session_id=self._safe_session_id(),
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="success",
                error_type=None,
                error_message=None,
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)

    async def _run_error_hooks(self, _exc: Exception, _cmd: InvokeHandler | ExecuteJob) -> None:
        """No-op stub for error hooks. Hook registration wired in #268."""
        pass

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_listener(self, registration: ListenerRegistration) -> int:
        """Upsert a listener registration into the listeners table.

        On conflict with the same natural key (app_key, instance_index, handler_method, topic),
        only last_registered_at is updated — first_registered_at is never changed.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted or updated row.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        return await self.hassette.database_service.submit(self._do_register_listener(registration))

    async def _do_register_listener(self, registration: ListenerRegistration) -> int:
        """Execute the listener INSERT OR CONFLICT SQL; called by the DB write-queue worker.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted or updated row.
        """
        db = self.hassette.database_service.db
        cursor = await db.execute(
            """
            INSERT INTO listeners (
                app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                predicate_description, human_description,
                source_location, registration_source,
                first_registered_at, last_registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (app_key, instance_index, handler_method, topic)
            DO UPDATE SET
                last_registered_at = excluded.last_registered_at,
                human_description = excluded.human_description
            RETURNING id
            """,
            (
                registration.app_key,
                registration.instance_index,
                registration.handler_method,
                registration.topic,
                registration.debounce,
                registration.throttle,
                1 if registration.once else 0,
                registration.priority,
                registration.predicate_description,
                registration.human_description,
                registration.source_location,
                registration.registration_source,
                registration.first_registered_at,
                registration.last_registered_at,
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO listeners — this should never happen")
        return row[0]

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Upsert a scheduled job registration into the scheduled_jobs table.

        On conflict with the same natural key (app_key, instance_index, job_name),
        only last_registered_at is updated.

        Args:
            registration: The scheduled job registration data.

        Returns:
            The row ID of the inserted or updated row.
        """
        await self.hassette.wait_for_ready([self.hassette.database_service])
        return await self.hassette.database_service.submit(self._do_register_job(registration))

    async def _do_register_job(self, registration: ScheduledJobRegistration) -> int:
        """Execute the scheduled_jobs INSERT OR CONFLICT SQL; called by the DB write-queue worker.

        Args:
            registration: The scheduled job registration data.

        Returns:
            The row ID of the inserted or updated row.
        """
        db = self.hassette.database_service.db
        cursor = await db.execute(
            """
            INSERT INTO scheduled_jobs (
                app_key, instance_index, job_name, handler_method,
                trigger_type, trigger_value, repeat,
                args_json, kwargs_json,
                source_location, registration_source,
                first_registered_at, last_registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (app_key, instance_index, job_name)
            DO UPDATE SET last_registered_at = excluded.last_registered_at
            RETURNING id
            """,
            (
                registration.app_key,
                registration.instance_index,
                registration.job_name,
                registration.handler_method,
                registration.trigger_type,
                registration.trigger_value,
                1 if registration.repeat else 0,
                registration.args_json,
                registration.kwargs_json,
                registration.source_location,
                registration.registration_source,
                registration.first_registered_at,
                registration.last_registered_at,
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO scheduled_jobs — should never happen")
        return row[0]

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
        await self.hassette.database_service.submit(self._do_clear_registrations(app_key))

    async def _do_clear_registrations(self, app_key: str) -> None:
        """Execute the DELETE SQL for clearing registrations; called by DB write-queue worker."""
        db = self.hassette.database_service.db
        await db.execute("DELETE FROM listeners WHERE app_key = ?", (app_key,))
        await db.execute("DELETE FROM scheduled_jobs WHERE app_key = ?", (app_key,))
        await db.commit()

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

        Args:
            invocations: Handler invocation records to insert into handler_invocations.
            job_executions: Job execution records to insert into job_executions.
        """
        await self.hassette.database_service.submit(self._do_persist_batch(invocations, job_executions))

    async def _do_persist_batch(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> None:
        """Execute the executemany inserts for a batch of records; called by the DB write-queue worker.

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

        if not invocations and not job_executions:
            return

        db = self.hassette.database_service.db

        if invocations:
            await db.executemany(
                """
                INSERT INTO handler_invocations (
                    listener_id, session_id, execution_start_ts,
                    duration_ms, status, error_type, error_message, error_traceback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.listener_id,
                        r.session_id,
                        r.execution_start_ts,
                        r.duration_ms,
                        r.status,
                        r.error_type,
                        r.error_message,
                        r.error_traceback,
                    )
                    for r in invocations
                ],
            )

        if job_executions:
            await db.executemany(
                """
                INSERT INTO job_executions (
                    job_id, session_id, execution_start_ts,
                    duration_ms, status, error_type, error_message, error_traceback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        r.job_id,
                        r.session_id,
                        r.execution_start_ts,
                        r.duration_ms,
                        r.status,
                        r.error_type,
                        r.error_message,
                        r.error_traceback,
                    )
                    for r in job_executions
                ],
            )

        await db.commit()
