"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import sqlite3
import time
from logging import Logger, getLogger
from typing import TYPE_CHECKING, Any

from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_models import BlockingEvent
from hassette.types.types import is_framework_key

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
    import aiosqlite

    from hassette.core.database_service import DatabaseService


def _execution_insert_params(record: ExecutionRecord) -> dict[str, Any]:
    """Build the named-parameter dict for an executions INSERT.

    All booleans are converted to int (SQLite has no native bool type).
    Columns match the ``executions`` table schema (001.sql original; 004.sql adds ``thread_leaked``).

    Args:
        record: The unified execution record to convert.

    Returns:
        A dict of named parameters ready for ``db.execute()`` or
        ``db.executemany()``.
    """
    return {
        "kind": record.kind,
        "listener_id": record.listener_id,
        "job_id": record.job_id,
        "session_id": record.session_id,
        "execution_start_ts": record.execution_start_ts,
        "duration_ms": record.duration_ms,
        "status": record.status,
        "error_type": record.error_type,
        "error_message": record.error_message,
        "error_traceback": record.error_traceback,
        "is_di_failure": 1 if record.is_di_failure else 0,
        "source_tier": record.source_tier,
        "execution_id": record.execution_id,
        "trigger_context_id": record.trigger_context_id,
        "trigger_origin": record.trigger_origin,
        "trigger_mode": record.trigger_mode,
        "retry_count": record.retry_count,
        "attempt_number": record.attempt_number,
        "args_json": record.args_json,
        "kwargs_json": record.kwargs_json,
        "thread_leaked": 1 if record.thread_leaked else 0,
    }


# Every execution row inserts the same columns, so derive the INSERT statement once from a
# representative record's parameter keys. The batch and FK-fallback paths share this constant,
# which makes it impossible for them to build mismatched column lists.
_EXECUTION_INSERT_COLUMNS = tuple(
    _execution_insert_params(
        ExecutionRecord(kind="handler", session_id=None, execution_start_ts=0.0, duration_ms=0.0, status="success")
    )
)
_EXECUTION_INSERT_SQL = (
    f"INSERT INTO executions ({', '.join(_EXECUTION_INSERT_COLUMNS)}) "
    f"VALUES ({', '.join(f':{c}' for c in _EXECUTION_INSERT_COLUMNS)})"
)


def _is_fk_violation(exc: sqlite3.IntegrityError) -> bool:
    """Return True if the IntegrityError is a foreign key constraint violation.

    SQLite error messages for FK violations contain "FOREIGN KEY". Other
    IntegrityError subtypes (CHECK, NOT NULL, UNIQUE) use different messages.
    """
    return "FOREIGN KEY" in str(exc).upper()


def _listener_insert_params(registration: ListenerRegistration) -> dict[str, Any]:
    """Build the named-parameter dict for a listeners INSERT.

    Args:
        registration: The listener registration data.

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
        "once": 1 if registration.once else 0,
        "priority": registration.priority,
        "predicate_description": registration.predicate_description,
        "human_description": registration.human_description,
        "source_location": registration.source_location,
        "registration_source": registration.registration_source,
        "name": registration.name or "",
        "source_tier": registration.source_tier,
        "immediate": 1 if registration.immediate else 0,
        "duration": registration.duration,
        "entity_id": registration.entity_id,
        "mode": registration.mode,
        "backpressure": registration.backpressure,
    }


async def _insert_row_with_fk_fallback(
    db: "aiosqlite.Connection",
    record_params: dict,
    fk_field: str,
    logger: Logger,
) -> bool:
    """Try to INSERT one row into executions; on FK violation, null the FK field and retry.

    Args:
        db: An open aiosqlite connection.
        record_params: Named-parameter dict for the initial INSERT attempt.
        fk_field: The FK column name to null on violation (``"listener_id"`` or ``"job_id"``).
        logger: Logger instance for warning/error messages.

    Returns:
        True if the row was dropped (failed even after nulling FK), False on success.
    """
    try:
        await db.execute(_EXECUTION_INSERT_SQL, record_params)
        return False
    except sqlite3.IntegrityError as exc:
        if not _is_fk_violation(exc):
            logger.error(
                "Non-FK IntegrityError on executions row (%s=%s) — dropping: %s",
                fk_field,
                record_params.get(fk_field),
                exc,
            )
            return True
        logger.warning(
            "FK violation on executions row (%s=%s) — nulling FK and retrying",
            fk_field,
            record_params.get(fk_field),
        )
        nulled_params = {**record_params, fk_field: None}
        try:
            await db.execute(_EXECUTION_INSERT_SQL, nulled_params)
            return False
        except sqlite3.IntegrityError as retry_exc:
            logger.error(
                "Failed to persist executions row even with null FK — dropping: %s",
                retry_exc,
            )
            return True


# The reconciliation query builders interpolate ``table`` and ``history_fk`` directly into
# f-string SQL. Today every caller passes string literals, but an allowlist keeps that
# interpolation injection-safe if a non-literal value is ever passed in.
_RECONCILE_TABLES = frozenset({"listeners", "scheduled_jobs"})
_RECONCILE_FK_COLUMNS = frozenset({"listener_id", "job_id"})


def _assert_reconcile_identifiers(table: str, history_fk: str) -> None:
    if table not in _RECONCILE_TABLES or history_fk not in _RECONCILE_FK_COLUMNS:
        raise ValueError(f"Refusing to build SQL for unknown identifiers: table={table!r}, history_fk={history_fk!r}")


def _build_delete_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    extra_where: str = "",
) -> tuple[str, dict]:
    """Build a DELETE query that removes rows not in ``live_ids`` without history.

    Args:
        table: Table to delete from (e.g. ``"listeners"``).
        app_key: The app key to scope the DELETE.
        live_ids: IDs to exclude from deletion.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key}
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
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


def _build_retire_query(
    table: str,
    app_key: str,
    live_ids: list[int],
    history_fk: str,
    now: float,
    extra_where: str = "",
) -> tuple[str, dict]:
    """Build an UPDATE query that sets ``retired_at`` for rows not in ``live_ids`` with history.

    Args:
        table: Table to update (e.g. ``"listeners"``).
        app_key: The app key to scope the UPDATE.
        live_ids: IDs to exclude from retirement.
        history_fk: FK column in the executions table (e.g. ``"listener_id"``).
        now: Epoch timestamp for ``retired_at``.
        extra_where: Optional additional WHERE fragment (leading ``AND`` included).

    Returns:
        A ``(sql, params)`` tuple.
    """
    _assert_reconcile_identifiers(table, history_fk)
    params: dict[str, Any] = {"app_key": app_key, "now": now}
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
              SELECT 1 FROM executions WHERE {history_fk} = {table}.id
          )
    """
    return sql, params


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

        Uses ``INSERT ... ON CONFLICT DO UPDATE`` to preserve the row ID across
        restarts (FK preservation). The conflict target exactly matches the unique
        index ``idx_listeners_natural ON listeners(app_key, instance_index, name, topic)``.
        Mutable fields are updated on conflict; identity fields are left unchanged.
        ``retired_at`` is reset to NULL when a retired row is re-registered.

        Both once=True and once=False listeners participate in the same upsert path.
        The unique index covers all listeners; once=True listeners with a non-empty
        stable name can still benefit from ID preservation across restarts.

        Args:
            registration: The listener registration data.

        Returns:
            The row ID of the inserted (or matched) row.

        Raises:
            RuntimeError: If the RETURNING clause returns no row (should never happen).
        """
        db = self._db_service.db

        cursor = await db.execute(
            """
            INSERT INTO listeners (
                app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                predicate_description, human_description,
                source_location, registration_source, name, source_tier,
                immediate, duration, entity_id, mode, backpressure
            ) VALUES (
                :app_key, :instance_index, :handler_method, :topic,
                :debounce, :throttle, :once, :priority,
                :predicate_description, :human_description,
                :source_location, :registration_source, :name, :source_tier,
                :immediate, :duration, :entity_id, :mode, :backpressure
            )
            ON CONFLICT(app_key, instance_index, name, topic)
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
                mode = excluded.mode,
                backpressure = excluded.backpressure,
                retired_at = NULL,
                cancelled_at = NULL  -- re-registration clears cancellation
            RETURNING id
            """,
            _listener_insert_params(registration),
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
                "group", name_auto, mode
            ) VALUES (
                :app_key, :instance_index, :job_name, :handler_method,
                :trigger_type,
                :trigger_label, :trigger_detail,
                :repeat,
                :args_json, :kwargs_json,
                :source_location, :registration_source, :source_tier,
                :group, :name_auto, :mode
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
                name_auto = excluded.name_auto,
                mode = excluded.mode,
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
                "name_auto": int(registration.name_auto),
                "mode": registration.mode,
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

    async def mark_listener_cancelled(self, db_id: int) -> None:
        """Set ``cancelled_at`` to the current epoch time for the given listener row.

        Called from the cancel path in ``BusService`` when a listener is cancelled
        so that the durable ``cancelled`` state survives memory removal.

        Args:
            db_id: The ``id`` of the ``listeners`` row to mark as cancelled.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE listeners SET cancelled_at = :cancelled_at WHERE id = :id",
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
        - Rows without execution history in ``executions`` are deleted outright.
        - Rows with history have ``retired_at`` set to the current time.

        For once=True listeners not in the live ID set and not in the current session,
        deletes them (guarded by NOT EXISTS for current-session executions).

        Args:
            app_key: The app key to reconcile.
            live_listener_ids: IDs of currently active listener rows.
            live_job_ids: IDs of currently active scheduled_job rows.
            session_id: Current session ID, used to guard once=True row deletion.
                When None, once=True rows are unconditionally deleted.
        """
        if is_framework_key(app_key):
            LOGGER.warning(
                "reconcile_registrations() called for app_key=%r — framework listeners are not reconciled; skipping",
                app_key,
            )
            return

        db = self._db_service.db
        now = time.time()

        try:
            # Explicit BEGIN — aiosqlite opens connections with isolation_level=None (autocommit),
            # so without this BEGIN, each execute() below auto-commits individually and the
            # rollback() in the except clause is a no-op.
            await db.execute("BEGIN")

            sql, params = _build_delete_query(
                "listeners",
                app_key,
                live_listener_ids,
                "listener_id",
                extra_where=" AND once = 0",
            )
            await db.execute(sql, params)

            sql, params = _build_retire_query(
                "listeners",
                app_key,
                live_listener_ids,
                "listener_id",
                now,
                extra_where=" AND once = 0",
            )
            await db.execute(sql, params)

            if session_id is not None:
                params_once: dict = {"app_key": app_key, "source_tier": "app", "session_id": session_id}
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
                          SELECT 1 FROM executions
                          WHERE listener_id = listeners.id AND session_id = :session_id
                      )
                    """,
                    params_once,
                )
            else:
                # session_id is unavailable (DB write queue backpressure at startup).
                # Skip once=True deletion entirely — any row that fired before reconciliation
                # but whose execution hasn't flushed yet would be orphaned without the
                # session-scoped NOT EXISTS guard. Defer cleanup to the next successful restart.
                LOGGER.debug(
                    "session_id unavailable for app '%s' — skipping once=True cleanup; deferred to next restart",
                    app_key,
                )

            sql, params = _build_delete_query(
                "scheduled_jobs",
                app_key,
                live_job_ids,
                "job_id",
            )
            await db.execute(sql, params)

            sql, params = _build_retire_query(
                "scheduled_jobs",
                app_key,
                live_job_ids,
                "job_id",
                now,
            )
            await db.execute(sql, params)

            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def insert_blocking_event(self, event: BlockingEvent) -> None:
        """Insert a single blocking event row into the ``blocking_events`` table.

        Each detected Tier 1 or Tier 2 event produces exactly one row. No batching —
        blocking events are normally rare, so the overhead of one INSERT per event is
        acceptable. A DB write failure (disk full, lock contention) is logged here with
        app attribution and the row is dropped, rather than propagating as an
        unattributed "Unhandled error in enqueued DB write" from the write worker.

        Args:
            event: The ``BlockingEvent`` record to persist.
        """
        db = self._db_service.db
        try:
            await db.execute(
                """
                INSERT INTO blocking_events (
                    session_id, app_key, instance_name, instance_index,
                    execution_id, tier, primitive, source_location,
                    stall_duration_ms, detected_ts, source_tier, reason
                ) VALUES (
                    :session_id, :app_key, :instance_name, :instance_index,
                    :execution_id, :tier, :primitive, :source_location,
                    :stall_duration_ms, :detected_ts, :source_tier, :reason
                )
                """,
                {
                    "session_id": event.session_id,
                    "app_key": event.app_key,
                    "instance_name": event.instance_name,
                    "instance_index": event.instance_index,
                    "execution_id": event.execution_id,
                    "tier": event.tier,
                    "primitive": event.primitive,
                    "source_location": event.source_location,
                    "stall_duration_ms": event.stall_duration_ms,
                    "detected_ts": event.detected_ts,
                    "source_tier": event.source_tier,
                    "reason": event.reason,
                },
            )
            await db.commit()
        except Exception:
            LOGGER.warning(
                "Dropped blocking_events row (DB write failed) — tier=%s app=%s primitive=%s",
                event.tier,
                event.app_key,
                event.primitive,
                exc_info=True,
            )

    async def persist_execution_batch(self, records: list[ExecutionRecord]) -> None:
        """Write a batch of unified execution records to the executions table.

        Args:
            records: Execution records to insert. All must have session_id set.
        """
        if not records:
            return

        db = self._db_service.db

        try:
            await db.execute("BEGIN")
            params_list = [_execution_insert_params(r) for r in records]
            await db.executemany(_EXECUTION_INSERT_SQL, params_list)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def persist_execution_batch_with_fk_fallback(self, records: list[ExecutionRecord]) -> int:
        """Insert execution records row-by-row with FK violation fallback (best-effort per record).

        Called by ``CommandExecutor.handle_fk_violation`` after a batch INSERT already
        failed with IntegrityError. Each record is inserted individually; on FK violation
        the FK field is nulled and retried. Runs as one ``submit()`` call on the DB write
        queue, avoiding N round-trips.

        Atomicity is best-effort per record: if an individual record fails even after FK
        nulling, it is silently dropped and remaining records are still committed.

        Returns the number of records that were dropped (failed even with null FK).
        """
        db = self._db_service.db
        dropped = 0

        if not records:
            return 0

        try:
            await db.execute("BEGIN")

            for record in records:
                params = _execution_insert_params(record)
                fk_field = "listener_id" if record.kind == "handler" else "job_id"
                if await _insert_row_with_fk_fallback(db, params, fk_field, LOGGER):
                    dropped += 1

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return dropped
