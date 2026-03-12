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
        on_initialize(): waits for DatabaseService to be ready, sets session_id.
        serve(): drains the write queue in batches until shutdown, then flushes remaining records.

    Records are queued immediately after each execution and persisted in batches by serve().
    On shutdown, _flush_queue() persists any remaining records before returning.
    """

    _write_queue: asyncio.Queue[HandlerInvocationRecord | JobExecutionRecord]
    """Unbounded queue of execution records pending DB persistence."""

    _session_id: int
    """Session ID for the current Hassette session. Set during on_initialize()."""

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
        """Wait for DatabaseService to be ready, then capture the session ID."""
        await self.hassette.wait_for_ready([self.hassette.database_service])
        self._session_id = self.hassette.session_id

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
                # If the get_fut completed and put an item back, we need to put it back
                if get_fut in done and not get_fut.cancelled() and get_fut.exception() is None:
                    result = get_fut.result()
                    self._write_queue.put_nowait(result)
                await self._flush_queue()
                return

            # Queue has an item — put it back and drain the full queue in one batch
            if get_fut in done and not get_fut.cancelled() and get_fut.exception() is None:
                self._write_queue.put_nowait(get_fut.result())
                await self._drain_and_persist()

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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
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
                session_id=self._session_id,
                execution_start_ts=execution_start_ts,
                duration_ms=duration_ms,
                status="success",
                error_type=None,
                error_message=None,
                error_traceback=None,
            )
            self._write_queue.put_nowait(record)

    async def _run_error_hooks(self, exc: Exception, cmd: InvokeHandler | ExecuteJob) -> None:
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
        db = self.hassette.database_service.db
        cursor = await db.execute(
            """
            INSERT INTO listeners (
                app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                predicate_description, source_location, registration_source,
                first_registered_at, last_registered_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (app_key, instance_index, handler_method, topic)
            DO UPDATE SET last_registered_at = excluded.last_registered_at
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
    # Queue persistence
    # ------------------------------------------------------------------

    async def _drain_and_persist(self) -> None:
        """Drain up to 100 items from the write queue and persist them to DB.

        Separates HandlerInvocationRecord and JobExecutionRecord items into
        separate batches, writing each with executemany in a single transaction.
        """
        invocations: list[HandlerInvocationRecord] = []
        job_executions: list[JobExecutionRecord] = []

        # Drain up to 100 items (non-blocking after the first)
        for _ in range(100):
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
        # Filter out records with unregistered IDs (id=0 sentinel means the handler fired before
        # register_listener/register_job completed — a startup race). Log and drop rather than
        # violate the FK constraint.
        unregistered_invocations = [r for r in invocations if r.listener_id == 0]
        unregistered_jobs = [r for r in job_executions if r.job_id == 0]
        if unregistered_invocations:
            self.logger.warning(
                "Dropping %d handler invocation record(s) with listener_id=0 (fired before registration completed)",
                len(unregistered_invocations),
            )
        if unregistered_jobs:
            self.logger.warning(
                "Dropping %d job execution record(s) with job_id=0 (fired before registration completed)",
                len(unregistered_jobs),
            )
        invocations = [r for r in invocations if r.listener_id != 0]
        job_executions = [r for r in job_executions if r.job_id != 0]

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
