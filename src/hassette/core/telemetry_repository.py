"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import typing

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.scheduler.classes import JobExecutionRecord

if typing.TYPE_CHECKING:
    from hassette.core.database_service import DatabaseService


class TelemetryRepository:
    """Encapsulates all write-side SQL for handler and job telemetry.

    Holds a reference to ``DatabaseService`` and accesses ``db`` lazily inside
    each coroutine body — never at construction time or call sites — so that
    the repository is safe to instantiate before the database is ready.

    All methods are coroutines intended to be submitted via
    ``DatabaseService.submit(self.repository.method(...))``.
    """

    def __init__(self, db_service: "DatabaseService") -> None:
        self._db_service = db_service

    async def register_listener(self, registration: ListenerRegistration) -> int:
        """Upsert a listener registration into the listeners table.

        For ``once=False`` listeners, uses ``INSERT ... ON CONFLICT DO UPDATE`` to
        preserve the row ID across restarts (FK preservation). Mutable fields are
        updated on conflict; identity fields (including ``human_description`` and
        ``name``) are left unchanged. ``retired_at`` is reset to NULL when a retired
        row is re-registered.

        For ``once=True`` listeners, uses a plain ``INSERT`` — these are ephemeral
        and are excluded from the partial unique index, so the upsert path does not
        apply.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted (or matched) row.

        Raises:
            RuntimeError: If the RETURNING clause returns no row (should never happen).
        """
        db = self._db_service.db

        if registration.once:
            # once=True listeners: always insert fresh — partial index (WHERE once = 0)
            # excludes them from uniqueness enforcement, so ON CONFLICT would never fire.
            cursor = await db.execute(
                """
                INSERT INTO listeners (
                    app_key, instance_index, handler_method, topic,
                    debounce, throttle, once, priority,
                    predicate_description, human_description,
                    source_location, registration_source, name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    registration.app_key,
                    registration.instance_index,
                    registration.handler_method,
                    registration.topic,
                    registration.debounce,
                    registration.throttle,
                    1,
                    registration.priority,
                    registration.predicate_description,
                    registration.human_description,
                    registration.source_location,
                    registration.registration_source,
                    registration.name,
                ),
            )
        else:
            # once=False listeners: upsert — return existing ID on conflict so FK
            # references in handler_invocations survive across restarts.
            cursor = await db.execute(
                """
                INSERT INTO listeners (
                    app_key, instance_index, handler_method, topic,
                    debounce, throttle, once, priority,
                    predicate_description, human_description,
                    source_location, registration_source, name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
                WHERE once = 0
                DO UPDATE SET
                    debounce = excluded.debounce,
                    throttle = excluded.throttle,
                    priority = excluded.priority,
                    predicate_description = excluded.predicate_description,
                    source_location = excluded.source_location,
                    registration_source = excluded.registration_source,
                    retired_at = NULL
                RETURNING id
                """,
                (
                    registration.app_key,
                    registration.instance_index,
                    registration.handler_method,
                    registration.topic,
                    registration.debounce,
                    registration.throttle,
                    0,
                    registration.priority,
                    registration.predicate_description,
                    registration.human_description,
                    registration.source_location,
                    registration.registration_source,
                    registration.name,
                ),
            )

        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO listeners — this should never happen")
        return row[0]

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Upsert a scheduled job registration into the scheduled_jobs table.

        Uses ``INSERT ... ON CONFLICT DO UPDATE`` to preserve the row ID across
        restarts (FK preservation). Mutable fields are updated on conflict;
        ``job_name`` (the natural key component) is left unchanged.
        ``retired_at`` is reset to NULL when a retired row is re-registered.

        Args:
            registration: The scheduled job registration data.

        Returns:
            The row ID of the inserted (or matched) row.

        Raises:
            RuntimeError: If the RETURNING clause returns no row (should never happen).
        """
        db = self._db_service.db
        cursor = await db.execute(
            """
            INSERT INTO scheduled_jobs (
                app_key, instance_index, job_name, handler_method,
                trigger_type, trigger_value, repeat,
                args_json, kwargs_json,
                source_location, registration_source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(app_key, instance_index, job_name)
            DO UPDATE SET
                handler_method = excluded.handler_method,
                trigger_type = excluded.trigger_type,
                trigger_value = excluded.trigger_value,
                repeat = excluded.repeat,
                args_json = excluded.args_json,
                kwargs_json = excluded.kwargs_json,
                source_location = excluded.source_location,
                registration_source = excluded.registration_source,
                retired_at = NULL
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
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO scheduled_jobs — should never happen")
        return row[0]

    async def clear_registrations(self, app_key: str) -> None:
        """Delete all listener and scheduled job registrations for an app.

        History rows (handler_invocations, job_executions) are preserved with
        NULL parent references via ON DELETE SET NULL.

        Args:
            app_key: The app key whose registrations to delete.
        """
        db = self._db_service.db
        try:
            await db.execute("DELETE FROM listeners WHERE app_key = ?", (app_key,))
            await db.execute("DELETE FROM scheduled_jobs WHERE app_key = ?", (app_key,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def persist_batch(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> None:
        """Write a batch of execution records to the DB in a single transaction.

        Sentinel filtering (listener_id == 0, session_id == 0) is performed by
        the caller (``CommandExecutor._drain_and_persist``) before calling this
        method. This method writes all records it receives without additional
        filtering.

        Args:
            invocations: Handler invocation records to insert into handler_invocations.
            job_executions: Job execution records to insert into job_executions.
        """
        if not invocations and not job_executions:
            return

        db = self._db_service.db

        try:
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
        except Exception:
            await db.rollback()
            raise
