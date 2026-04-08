"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import logging
import sqlite3
import time
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
                    source_location, registration_source, name, source_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    registration.source_tier,
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
                    source_location, registration_source, name, source_tier
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    registration.source_tier,
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
                source_location, registration_source, source_tier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                registration.source_tier,
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO scheduled_jobs — should never happen")
        return row[0]

    async def reconcile_registrations(
        self,
        app_key: str,
        live_listener_ids: list[int],
        live_job_ids: list[int],
        *,
        session_id: int | None = None,
    ) -> None:
        """Reconcile listener and job registrations for an app after initialization.

        For non-once listeners and jobs not in the live ID sets:
        - Rows without invocation/execution history are deleted outright.
        - Rows with history have ``retired_at`` set to the current time.

        For once=True listeners not in the live ID set and not in the current session,
        deletes them (guarded by NOT EXISTS for current-session invocations).

        Args:
            app_key: The app key to reconcile.
            live_listener_ids: IDs of currently active listener rows.
            live_job_ids: IDs of currently active scheduled_job rows.
            session_id: Current session ID, used to guard once=True row deletion.
                When None, once=True rows are unconditionally deleted.
        """
        if app_key == "__hassette__":
            logging.getLogger(__name__).warning(
                "reconcile_registrations() called for app_key='__hassette__' — "
                "framework listeners are not reconciled; skipping"
            )
            return

        db = self._db_service.db
        now = time.time()

        try:
            # --- Non-once listeners without history: delete ---
            if live_listener_ids:
                placeholders = ",".join("?" * len(live_listener_ids))
                await db.execute(
                    f"""
                    DELETE FROM listeners
                    WHERE app_key = ? AND once = 0
                      AND id NOT IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM handler_invocations WHERE listener_id = listeners.id
                      )
                    """,
                    (app_key, *live_listener_ids),
                )
            else:
                await db.execute(
                    """
                    DELETE FROM listeners
                    WHERE app_key = ? AND once = 0
                      AND NOT EXISTS (
                          SELECT 1 FROM handler_invocations WHERE listener_id = listeners.id
                      )
                    """,
                    (app_key,),
                )

            # --- Non-once listeners with history: retire ---
            if live_listener_ids:
                placeholders = ",".join("?" * len(live_listener_ids))
                await db.execute(
                    f"""
                    UPDATE listeners SET retired_at = ?
                    WHERE app_key = ? AND once = 0
                      AND id NOT IN ({placeholders})
                      AND retired_at IS NULL
                      AND EXISTS (
                          SELECT 1 FROM handler_invocations WHERE listener_id = listeners.id
                      )
                    """,
                    (now, app_key, *live_listener_ids),
                )
            else:
                await db.execute(
                    """
                    UPDATE listeners SET retired_at = ?
                    WHERE app_key = ? AND once = 0
                      AND retired_at IS NULL
                      AND EXISTS (
                          SELECT 1 FROM handler_invocations WHERE listener_id = listeners.id
                      )
                    """,
                    (now, app_key),
                )

            # --- once=True listeners: delete from previous sessions ---
            if session_id is not None:
                if live_listener_ids:
                    placeholders = ",".join("?" * len(live_listener_ids))
                    await db.execute(
                        f"""
                        DELETE FROM listeners
                        WHERE app_key = ? AND once = 1
                          AND source_tier = 'app'
                          AND id NOT IN ({placeholders})
                          AND NOT EXISTS (
                              SELECT 1 FROM handler_invocations
                              WHERE listener_id = listeners.id AND session_id = ?
                          )
                        """,
                        (app_key, *live_listener_ids, session_id),
                    )
                else:
                    await db.execute(
                        """
                        DELETE FROM listeners
                        WHERE app_key = ? AND once = 1
                          AND source_tier = 'app'
                          AND NOT EXISTS (
                              SELECT 1 FROM handler_invocations
                              WHERE listener_id = listeners.id AND session_id = ?
                          )
                        """,
                        (app_key, session_id),
                    )
            else:
                # session_id is unavailable (DB write queue backpressure at startup).
                # Skip once=True deletion entirely — any row that fired before reconciliation
                # but whose invocation hasn't flushed yet would be orphaned without the
                # session-scoped NOT EXISTS guard. Defer cleanup to the next successful restart.
                # This condition is correlated with heavy-load scenarios where the risk is real.
                logging.getLogger(__name__).debug(
                    "session_id unavailable for app '%s' — skipping once=True cleanup; deferred to next restart",
                    app_key,
                )

            # --- Non-once jobs without history: delete ---
            if live_job_ids:
                placeholders = ",".join("?" * len(live_job_ids))
                await db.execute(
                    f"""
                    DELETE FROM scheduled_jobs
                    WHERE app_key = ? AND id NOT IN ({placeholders})
                      AND NOT EXISTS (
                          SELECT 1 FROM job_executions WHERE job_id = scheduled_jobs.id
                      )
                    """,
                    (app_key, *live_job_ids),
                )
            else:
                await db.execute(
                    """
                    DELETE FROM scheduled_jobs
                    WHERE app_key = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM job_executions WHERE job_id = scheduled_jobs.id
                      )
                    """,
                    (app_key,),
                )

            # --- Non-once jobs with history: retire ---
            if live_job_ids:
                placeholders = ",".join("?" * len(live_job_ids))
                await db.execute(
                    f"""
                    UPDATE scheduled_jobs SET retired_at = ?
                    WHERE app_key = ? AND id NOT IN ({placeholders})
                      AND retired_at IS NULL
                      AND EXISTS (
                          SELECT 1 FROM job_executions WHERE job_id = scheduled_jobs.id
                      )
                    """,
                    (now, app_key, *live_job_ids),
                )
            else:
                await db.execute(
                    """
                    UPDATE scheduled_jobs SET retired_at = ?
                    WHERE app_key = ?
                      AND retired_at IS NULL
                      AND EXISTS (
                          SELECT 1 FROM job_executions WHERE job_id = scheduled_jobs.id
                      )
                    """,
                    (now, app_key),
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def persist_batch_with_fk_fallback(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> int:
        """Write records with FK violation fallback — all within a single transaction.

        First attempts a batch insert. On IntegrityError, falls back to row-by-row
        insertion with FK fields nulled on violation. This runs as one submit() call
        on the DB write queue, avoiding N round-trips.

        Returns the number of records that were dropped (failed even with null FK).
        """
        db = self._db_service.db
        dropped = 0
        logger = logging.getLogger(__name__)

        try:
            await db.execute("BEGIN")
            # Try each invocation individually, nulling FK on violation
            for record in invocations:
                try:
                    await db.execute(
                        """
                        INSERT INTO handler_invocations (
                            listener_id, session_id, execution_start_ts,
                            duration_ms, status, source_tier, is_di_failure,
                            error_type, error_message, error_traceback
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.listener_id,
                            record.session_id,
                            record.execution_start_ts,
                            record.duration_ms,
                            record.status,
                            record.source_tier,
                            1 if record.is_di_failure else 0,
                            record.error_type,
                            record.error_message,
                            record.error_traceback,
                        ),
                    )
                except sqlite3.IntegrityError:
                    logger.warning(
                        "FK violation on handler_invocations row (listener_id=%s) — nulling FK and retrying",
                        record.listener_id,
                    )
                    try:
                        await db.execute(
                            """
                            INSERT INTO handler_invocations (
                                listener_id, session_id, execution_start_ts,
                                duration_ms, status, source_tier, is_di_failure,
                                error_type, error_message, error_traceback
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                None,
                                record.session_id,
                                record.execution_start_ts,
                                record.duration_ms,
                                record.status,
                                record.source_tier,
                                1 if record.is_di_failure else 0,
                                record.error_type,
                                record.error_message,
                                record.error_traceback,
                            ),
                        )
                    except Exception as exc:
                        dropped += 1
                        logger.error("Failed to persist handler_invocations row even with null FK — dropping: %s", exc)

            for record in job_executions:
                try:
                    await db.execute(
                        """
                        INSERT INTO job_executions (
                            job_id, session_id, execution_start_ts,
                            duration_ms, status, source_tier, is_di_failure,
                            error_type, error_message, error_traceback
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record.job_id,
                            record.session_id,
                            record.execution_start_ts,
                            record.duration_ms,
                            record.status,
                            record.source_tier,
                            1 if record.is_di_failure else 0,
                            record.error_type,
                            record.error_message,
                            record.error_traceback,
                        ),
                    )
                except sqlite3.IntegrityError:
                    logger.warning(
                        "FK violation on job_executions row (job_id=%s) — nulling FK and retrying",
                        record.job_id,
                    )
                    try:
                        await db.execute(
                            """
                            INSERT INTO job_executions (
                                job_id, session_id, execution_start_ts,
                                duration_ms, status, source_tier, is_di_failure,
                                error_type, error_message, error_traceback
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                None,
                                record.session_id,
                                record.execution_start_ts,
                                record.duration_ms,
                                record.status,
                                record.source_tier,
                                1 if record.is_di_failure else 0,
                                record.error_type,
                                record.error_message,
                                record.error_traceback,
                            ),
                        )
                    except Exception as exc:
                        dropped += 1
                        logger.error("Failed to persist job_executions row even with null FK — dropping: %s", exc)

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return dropped

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
                        duration_ms, status, source_tier, is_di_failure,
                        error_type, error_message, error_traceback
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            r.listener_id,
                            r.session_id,
                            r.execution_start_ts,
                            r.duration_ms,
                            r.status,
                            r.source_tier,
                            1 if r.is_di_failure else 0,
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
                        duration_ms, status, source_tier, is_di_failure,
                        error_type, error_message, error_traceback
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            r.job_id,
                            r.session_id,
                            r.execution_start_ts,
                            r.duration_ms,
                            r.status,
                            r.source_tier,
                            1 if r.is_di_failure else 0,
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
