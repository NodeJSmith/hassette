"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import logging
import sqlite3
import time
import typing

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.scheduler.classes import JobExecutionRecord
from hassette.types.types import is_framework_key

if typing.TYPE_CHECKING:
    import aiosqlite

    from hassette.core.database_service import DatabaseService


def _is_fk_violation(exc: sqlite3.IntegrityError) -> bool:
    """Return True if the IntegrityError is a foreign key constraint violation.

    SQLite error messages for FK violations contain "FOREIGN KEY". Other
    IntegrityError subtypes (CHECK, NOT NULL, UNIQUE) use different messages.
    """
    return "FOREIGN KEY" in str(exc).upper()


def _listener_params(registration: ListenerRegistration, once: bool) -> dict:
    """Build the named-parameter dict for a listeners INSERT.

    Args:
        registration: The listener registration data.
        once: Value to store in the ``once`` column (0 or 1).

    Returns:
        A dict of named parameters ready for ``db.execute()``.
    """
    return {
        "app_key": registration.app_key,
        "instance_index": registration.instance_index,
        "handler_method": registration.handler_method,
        "topic": registration.topic,
        "debounce": registration.debounce,
        "throttle": registration.throttle,
        "once": 1 if once else 0,
        "priority": registration.priority,
        "predicate_description": registration.predicate_description,
        "human_description": registration.human_description,
        "source_location": registration.source_location,
        "registration_source": registration.registration_source,
        "name": registration.name,
        "source_tier": registration.source_tier,
        "immediate": 1 if registration.immediate else 0,
        "duration": registration.duration,
        "entity_id": registration.entity_id,
    }


async def _insert_row_with_fk_fallback(
    db: "aiosqlite.Connection",
    table: str,
    columns: str,
    values_clause: str,
    record_params: dict,
    fk_field: str,
    logger: logging.Logger,
) -> int:
    """Try to INSERT one row; on FK violation, null the FK field and retry.

    This implements the try-FK-null-retry pattern used by
    ``persist_batch_with_fk_fallback`` for both handler_invocations and
    job_executions rows.

    Args:
        db: An open aiosqlite connection.
        table: Target table name (e.g. ``"handler_invocations"``).
        columns: Column list string for the INSERT.
        values_clause: Values clause string matching ``columns``.
        record_params: Named-parameter dict for the initial INSERT attempt.
        fk_field: The FK column name to null on violation (e.g. ``"listener_id"``).
        logger: Logger instance for warning/error messages.

    Returns:
        1 if the row was dropped (failed even after nulling FK), 0 on success.
    """
    sql = f"INSERT INTO {table} ({columns}) VALUES ({values_clause})"
    try:
        await db.execute(sql, record_params)
        return 0
    except sqlite3.IntegrityError as exc:
        if not _is_fk_violation(exc):
            logger.error(
                "Non-FK IntegrityError on %s row (%s=%s) — dropping: %s",
                table,
                fk_field,
                record_params.get(fk_field),
                exc,
            )
            return 1
        logger.warning(
            "FK violation on %s row (%s=%s) — nulling FK and retrying",
            table,
            fk_field,
            record_params.get(fk_field),
        )
        nulled_params = {**record_params, fk_field: None}
        try:
            await db.execute(sql, nulled_params)
            return 0
        except sqlite3.IntegrityError as retry_exc:
            logger.error(
                "Failed to persist %s row even with null FK — dropping: %s",
                table,
                retry_exc,
            )
            return 1


def _build_delete_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_table: str,
    history_fk: str,
    extra_where: str = "",
) -> tuple[str, dict]:
    """Build a DELETE query that removes rows not in ``live_ids`` without history.

    Args:
        table: Table to delete from (e.g. ``"listeners"``).
        app_key: The app key to scope the DELETE.
        live_ids: IDs to exclude from deletion.
        history_table: Related history table (e.g. ``"handler_invocations"``).
        history_fk: FK column in the history table (e.g. ``"listener_id"``).
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).

    Returns:
        A ``(sql, params)`` tuple.
    """
    params: dict = {"app_key": app_key}
    if live_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
        params.update({f"id_{i}": v for i, v in enumerate(live_ids)})
        not_in_clause = f"AND id NOT IN ({placeholders})"
    else:
        not_in_clause = ""

    sql = f"""
        DELETE FROM {table}
        WHERE app_key = :app_key{extra_where}
          {not_in_clause}
          AND NOT EXISTS (
              SELECT 1 FROM {history_table} WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


def _build_retire_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_table: str,
    history_fk: str,
    now: float,
    extra_where: str = "",
) -> tuple[str, dict]:
    """Build an UPDATE query that sets ``retired_at`` for rows not in ``live_ids`` with history.

    Args:
        table: Table to update (e.g. ``"listeners"``).
        app_key: The app key to scope the UPDATE.
        live_ids: IDs to exclude from retirement.
        history_table: Related history table (e.g. ``"handler_invocations"``).
        history_fk: FK column in the history table (e.g. ``"listener_id"``).
        now: Epoch timestamp for ``retired_at``.
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).

    Returns:
        A ``(sql, params)`` tuple.
    """
    params: dict = {"app_key": app_key, "now": now}
    if live_ids:
        placeholders = ", ".join(f":id_{i}" for i in range(len(live_ids)))
        params.update({f"id_{i}": v for i, v in enumerate(live_ids)})
        not_in_clause = f"AND id NOT IN ({placeholders})"
    else:
        not_in_clause = ""

    sql = f"""
        UPDATE {table} SET retired_at = :now
        WHERE app_key = :app_key{extra_where}
          {not_in_clause}
          AND retired_at IS NULL
          AND EXISTS (
              SELECT 1 FROM {history_table} WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


_TIER_APP: str = "app"


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
                    source_location, registration_source, name, source_tier,
                    immediate, duration, entity_id
                ) VALUES (
                    :app_key, :instance_index, :handler_method, :topic,
                    :debounce, :throttle, :once, :priority,
                    :predicate_description, :human_description,
                    :source_location, :registration_source, :name, :source_tier,
                    :immediate, :duration, :entity_id
                )
                RETURNING id
                """,
                _listener_params(registration, once=True),
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
                    source_location, registration_source, name, source_tier,
                    immediate, duration, entity_id
                ) VALUES (
                    :app_key, :instance_index, :handler_method, :topic,
                    :debounce, :throttle, :once, :priority,
                    :predicate_description, :human_description,
                    :source_location, :registration_source, :name, :source_tier,
                    :immediate, :duration, :entity_id
                )
                ON CONFLICT(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
                WHERE once = 0
                DO UPDATE SET
                    debounce = excluded.debounce,
                    throttle = excluded.throttle,
                    priority = excluded.priority,
                    predicate_description = excluded.predicate_description,
                    source_location = excluded.source_location,
                    registration_source = excluded.registration_source,
                    source_tier = excluded.source_tier,
                    immediate = excluded.immediate,
                    duration = excluded.duration,
                    entity_id = excluded.entity_id,
                    retired_at = NULL
                RETURNING id
                """,
                _listener_params(registration, once=False),
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
                trigger_type,
                trigger_label, trigger_detail,
                repeat,
                args_json, kwargs_json,
                source_location, registration_source, source_tier,
                "group"
            ) VALUES (
                :app_key, :instance_index, :job_name, :handler_method,
                :trigger_type,
                :trigger_label, :trigger_detail,
                :repeat,
                :args_json, :kwargs_json,
                :source_location, :registration_source, :source_tier,
                :group
            )
            ON CONFLICT(app_key, instance_index, job_name)
            DO UPDATE SET
                handler_method = excluded.handler_method,
                trigger_type = excluded.trigger_type,
                trigger_label = excluded.trigger_label,
                trigger_detail = excluded.trigger_detail,
                repeat = excluded.repeat,
                args_json = excluded.args_json,
                kwargs_json = excluded.kwargs_json,
                source_location = excluded.source_location,
                registration_source = excluded.registration_source,
                source_tier = excluded.source_tier,
                "group" = excluded."group",
                retired_at = NULL,
                cancelled_at = NULL  -- re-registration clears cancellation
            RETURNING id
            """,
            {
                "app_key": registration.app_key,
                "instance_index": registration.instance_index,
                "job_name": registration.job_name,
                "handler_method": registration.handler_method,
                "trigger_type": registration.trigger_type,
                "trigger_label": registration.trigger_label,
                "trigger_detail": registration.trigger_detail,
                "repeat": 0,  # repeat is always 0 for new-style jobs; triggers handle recurrence
                "args_json": registration.args_json,
                "kwargs_json": registration.kwargs_json,
                "source_location": registration.source_location,
                "registration_source": registration.registration_source,
                "source_tier": registration.source_tier,
                "group": registration.group,
            },
        )
        row = await cursor.fetchone()
        await db.commit()
        if row is None:
            raise RuntimeError("RETURNING id returned no row after INSERT INTO scheduled_jobs — should never happen")
        return row[0]

    async def mark_job_cancelled(self, db_id: int) -> None:
        """Set ``cancelled_at`` to the current epoch time for the given job row.

        Called from the cancel path in ``SchedulerService`` when a job is cancelled
        so that the durable ``cancelled`` state survives heap removal.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as cancelled.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE scheduled_jobs SET cancelled_at = :cancelled_at WHERE id = :id",
            {"cancelled_at": time.time(), "id": db_id},
        )
        await db.commit()

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
        if is_framework_key(app_key):
            logging.getLogger(__name__).warning(
                "reconcile_registrations() called for app_key=%r — framework listeners are not reconciled; skipping",
                app_key,
            )
            return

        db = self._db_service.db
        now = time.time()

        try:
            # Explicit BEGIN — aiosqlite opens connections with isolation_level=None (autocommit),
            # so without this BEGIN, each execute() below auto-commits individually and the
            # rollback() in the except clause is a no-op. This pattern mirrors
            # persist_batch_with_fk_fallback().
            await db.execute("BEGIN")

            # --- Non-once listeners without history: delete ---
            sql, params = _build_delete_query(
                "listeners",
                app_key,
                live_listener_ids,
                "handler_invocations",
                "listener_id",
                extra_where=" AND once = 0",
            )
            await db.execute(sql, params)

            # --- Non-once listeners with history: retire ---
            sql, params = _build_retire_query(
                "listeners",
                app_key,
                live_listener_ids,
                "handler_invocations",
                "listener_id",
                now,
                extra_where=" AND once = 0",
            )
            await db.execute(sql, params)

            # --- once=True listeners: delete from previous sessions ---
            if session_id is not None:
                params_once: dict = {"app_key": app_key, "source_tier": _TIER_APP, "session_id": session_id}
                if live_listener_ids:
                    placeholders = ", ".join(f":id_{i}" for i in range(len(live_listener_ids)))
                    params_once.update({f"id_{i}": v for i, v in enumerate(live_listener_ids)})
                    not_in_clause = f"AND id NOT IN ({placeholders})"
                else:
                    not_in_clause = ""
                await db.execute(
                    f"""
                    DELETE FROM listeners
                    WHERE app_key = :app_key AND once = 1
                      AND source_tier = :source_tier
                      {not_in_clause}
                      AND NOT EXISTS (
                          SELECT 1 FROM handler_invocations
                          WHERE listener_id = listeners.id AND session_id = :session_id
                      )
                    """,
                    params_once,
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
            sql, params = _build_delete_query(
                "scheduled_jobs",
                app_key,
                live_job_ids,
                "job_executions",
                "job_id",
            )
            await db.execute(sql, params)

            # --- Non-once jobs with history: retire ---
            sql, params = _build_retire_query(
                "scheduled_jobs",
                app_key,
                live_job_ids,
                "job_executions",
                "job_id",
                now,
            )
            await db.execute(sql, params)

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def persist_batch_with_fk_fallback(
        self,
        invocations: list[HandlerInvocationRecord],
        job_executions: list[JobExecutionRecord],
    ) -> int:
        """Insert records row-by-row with FK violation fallback (best-effort per record).

        Called by ``CommandExecutor._handle_fk_violation`` after a batch INSERT already
        failed with IntegrityError. Each record is inserted individually; on FK violation
        the FK field is nulled and retried. Runs as one ``submit()`` call on the DB write
        queue, avoiding N round-trips.

        Atomicity is best-effort per record, not per batch: if an individual record fails
        even after FK nulling (e.g. disk error), it is silently dropped and the remaining
        records are still committed. This is intentional for append-only telemetry — losing
        one record to a transient error is preferable to losing the entire batch.

        Returns the number of records that were dropped (failed even with null FK).
        """
        db = self._db_service.db
        dropped = 0
        logger = logging.getLogger(__name__)

        inv_cols = (
            "listener_id, session_id, execution_start_ts, "
            "duration_ms, status, source_tier, is_di_failure, "
            "error_type, error_message, error_traceback"
        )
        inv_vals = (
            ":listener_id, :session_id, :execution_start_ts, "
            ":duration_ms, :status, :source_tier, :is_di_failure, "
            ":error_type, :error_message, :error_traceback"
        )
        job_cols = (
            "job_id, session_id, execution_start_ts, "
            "duration_ms, status, source_tier, is_di_failure, "
            "error_type, error_message, error_traceback"
        )
        job_vals = (
            ":job_id, :session_id, :execution_start_ts, "
            ":duration_ms, :status, :source_tier, :is_di_failure, "
            ":error_type, :error_message, :error_traceback"
        )

        try:
            await db.execute("BEGIN")

            for record in invocations:
                params = {
                    "listener_id": record.listener_id,
                    "session_id": record.session_id,
                    "execution_start_ts": record.execution_start_ts,
                    "duration_ms": record.duration_ms,
                    "status": record.status,
                    "source_tier": record.source_tier,
                    "is_di_failure": 1 if record.is_di_failure else 0,
                    "error_type": record.error_type,
                    "error_message": record.error_message,
                    "error_traceback": record.error_traceback,
                }
                dropped += await _insert_row_with_fk_fallback(
                    db, "handler_invocations", inv_cols, inv_vals, params, "listener_id", logger
                )

            for record in job_executions:
                params = {
                    "job_id": record.job_id,
                    "session_id": record.session_id,
                    "execution_start_ts": record.execution_start_ts,
                    "duration_ms": record.duration_ms,
                    "status": record.status,
                    "source_tier": record.source_tier,
                    "is_di_failure": 1 if record.is_di_failure else 0,
                    "error_type": record.error_type,
                    "error_message": record.error_message,
                    "error_traceback": record.error_traceback,
                }
                dropped += await _insert_row_with_fk_fallback(
                    db, "job_executions", job_cols, job_vals, params, "job_id", logger
                )

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
                    ) VALUES (
                        :listener_id, :session_id, :execution_start_ts,
                        :duration_ms, :status, :source_tier, :is_di_failure,
                        :error_type, :error_message, :error_traceback
                    )
                    """,
                    [
                        {
                            "listener_id": r.listener_id,
                            "session_id": r.session_id,
                            "execution_start_ts": r.execution_start_ts,
                            "duration_ms": r.duration_ms,
                            "status": r.status,
                            "source_tier": r.source_tier,
                            "is_di_failure": 1 if r.is_di_failure else 0,
                            "error_type": r.error_type,
                            "error_message": r.error_message,
                            "error_traceback": r.error_traceback,
                        }
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
                    ) VALUES (
                        :job_id, :session_id, :execution_start_ts,
                        :duration_ms, :status, :source_tier, :is_di_failure,
                        :error_type, :error_message, :error_traceback
                    )
                    """,
                    [
                        {
                            "job_id": r.job_id,
                            "session_id": r.session_id,
                            "execution_start_ts": r.execution_start_ts,
                            "duration_ms": r.duration_ms,
                            "status": r.status,
                            "source_tier": r.source_tier,
                            "is_di_failure": 1 if r.is_di_failure else 0,
                            "error_type": r.error_type,
                            "error_message": r.error_message,
                            "error_traceback": r.error_traceback,
                        }
                        for r in job_executions
                    ],
                )

            await db.commit()
        except Exception:
            await db.rollback()
            raise
