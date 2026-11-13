"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import time
from logging import getLogger
from typing import TYPE_CHECKING

import orjson
from hassette_wire import ScheduleStatus, ScheduleStatusReason

from hassette.config.classes import AppManifest
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry.execution_queries import TRIGGER_COLUMNS
from hassette.core.telemetry.helpers import STORAGE_ERRORS
from hassette.core.telemetry.insert_params import (
    EXECUTION_INSERT_SQL,
    execution_insert_params,
    insert_row_with_fk_fallback,
    job_insert_params,
    listener_insert_params,
    manifest_insert_params,
)
from hassette.core.telemetry.reconcile_sql import (
    build_clear_stale_job_timing_query,
    build_delete_stale_jobs_query,
    build_retire_query,
)
from hassette.schemas.log_models import BlockingEvent
from hassette.types.types import is_framework_key
from hassette.utils.stack_frames import encode_frames

LOGGER = getLogger(__name__)


_LISTENER_MISS_LAST_COLUMNS = ("last_ts", *TRIGGER_COLUMNS)
"""``listener_misses`` columns that describe the last dropped event, replaced together by a newer rollup."""

_LISTENER_MISS_COLUMNS = (
    "listener_id",
    "hour_ts",
    "reason",
    "filter",
    "count",
    "first_ts",
    *_LISTENER_MISS_LAST_COLUMNS,
)

_LISTENER_MISS_LAST_SET = ", ".join(
    f"{column} = CASE WHEN excluded.last_ts >= last_ts THEN excluded.{column} ELSE {column} END"
    for column in _LISTENER_MISS_LAST_COLUMNS
)

# INSERT ... SELECT so a row whose listener was deleted since it was recorded inserts nothing. The SELECT's
# WHERE also keeps SQLite from parsing ON CONFLICT as a join constraint. Every SET expression reads the stored
# row's old values, so replacing last_ts doesn't change the CASE tests that follow it.
_LISTENER_MISS_UPSERT_SQL = f"""
    INSERT INTO listener_misses ({", ".join(_LISTENER_MISS_COLUMNS)})
    SELECT {", ".join(f":{column}" for column in _LISTENER_MISS_COLUMNS)}
    WHERE EXISTS (SELECT 1 FROM listeners WHERE id = :listener_id)
    ON CONFLICT(listener_id, hour_ts, reason, filter) DO UPDATE SET
        count = count + excluded.count,
        first_ts = MIN(first_ts, excluded.first_ts),
        {_LISTENER_MISS_LAST_SET}
"""


if TYPE_CHECKING:
    from hassette_wire import ApiWriteOutcome

    from hassette.core.api_write_recorder import ApiWriteRow
    from hassette.core.database_service import DatabaseService
    from hassette.core.listener_miss_recorder import ListenerMissRow


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
        index ``idx_listeners_natural ON listeners(app_key, instance_name, name, topic)``.
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
                app_key, instance_name, handler_method, topic,
                debounce, throttle, once, priority,
                predicate_description, human_description,
                source_location, registration_source, name, source_tier,
                immediate, duration, entity_id, mode, backpressure
            ) VALUES (
                :app_key, :instance_name, :handler_method, :topic,
                :debounce, :throttle, :once, :priority,
                :predicate_description, :human_description,
                :source_location, :registration_source, :name, :source_tier,
                :immediate, :duration, :entity_id, :mode, :backpressure
            )
            ON CONFLICT(app_key, instance_name, name, topic)
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
                removed_at = NULL  -- re-registration clears removal
            RETURNING id
            """,
            listener_insert_params(registration),
        )

        row = await cursor.fetchone()
        await db.commit()
        return row[0]  # pyright: ignore[reportOptionalSubscript] — RETURNING always yields one row

    async def register_job(self, registration: ScheduledJobRegistration) -> int:
        """Upsert a scheduled job registration into the scheduled_jobs table.

        Uses ``INSERT ... ON CONFLICT DO UPDATE`` to preserve the row ID across
        restarts (FK preservation). Mutable fields are updated on conflict;
        ``job_name`` (the natural key component) is left unchanged.
        ``retired_at`` is reset to NULL when a retired row is re-registered.

        The timing columns are overwritten on every registration, including back to NULL:
        ``next_run`` (unjittered next fire time, epoch seconds), ``fire_at`` (actual dispatch
        time after jitter, epoch seconds), and ``jitter`` (configured upper bound, seconds).
        Each is NULL when the job has no next occurrence or no jitter.

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
                app_key, instance_name, job_name, handler_method,
                trigger_type,
                trigger_label, trigger_detail,
                repeat,
                args_json, kwargs_json,
                source_location, registration_source, source_tier,
                "group", mode,
                predicate_description, human_description,
                schedule_status, schedule_status_reason,
                next_run, fire_at, jitter
            ) VALUES (
                :app_key, :instance_name, :job_name, :handler_method,
                :trigger_type,
                :trigger_label, :trigger_detail,
                :repeat,
                :args_json, :kwargs_json,
                :source_location, :registration_source, :source_tier,
                :group, :mode,
                :predicate_description, :human_description,
                :schedule_status, :schedule_status_reason,
                :next_run, :fire_at, :jitter
            )
            ON CONFLICT(app_key, instance_name, job_name)
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
                mode = excluded.mode,
                predicate_description = excluded.predicate_description,
                human_description = excluded.human_description,
                schedule_status = excluded.schedule_status,
                schedule_status_reason = excluded.schedule_status_reason,
                next_run = excluded.next_run,
                fire_at = excluded.fire_at,
                jitter = excluded.jitter,
                retired_at = NULL,
                removed_at = NULL  -- re-registration clears removal
            RETURNING id
            """,
            job_insert_params(registration),
        )
        row = await cursor.fetchone()
        await db.commit()
        return row[0]  # pyright: ignore[reportOptionalSubscript] — RETURNING always yields one row

    async def upsert_app_manifest(self, manifest: AppManifest) -> int:
        """Upsert an app manifest into the app_manifests table.

        Uses ``INSERT ... ON CONFLICT DO UPDATE`` keyed on ``app_key`` (simpler than the
        listener/job natural keys since manifests are per-app, not per-instance) to preserve
        the row ID across restarts. ``updated_at`` is explicitly set in the ``DO UPDATE SET``
        clause because the column ``DEFAULT`` expression only fires on INSERT, not on UPDATE.

        Args:
            manifest: The app manifest to persist.

        Returns:
            The row ID of the inserted (or matched) row.

        Raises:
            RuntimeError: If the RETURNING clause returns no row (should never happen).
        """
        db = self._db_service.db
        cursor = await db.execute(
            """
            INSERT INTO app_manifests (
                app_key, class_name, display_name, description, filename, enabled, autostart
            ) VALUES (
                :app_key, :class_name, :display_name, :description, :filename, :enabled, :autostart
            )
            ON CONFLICT(app_key)
            DO UPDATE SET
                class_name = excluded.class_name,
                display_name = excluded.display_name,
                description = excluded.description,
                filename = excluded.filename,
                enabled = excluded.enabled,
                autostart = excluded.autostart,
                updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')  -- format must match migrations_sql/011.sql
            RETURNING id
            """,
            manifest_insert_params(manifest),
        )
        row = await cursor.fetchone()
        await db.commit()
        return row[0]  # pyright: ignore[reportOptionalSubscript] — RETURNING always yields one row

    async def mark_job_removed(self, db_id: int) -> None:
        """Set ``removed_at`` to the current epoch time for the given job row.

        Called from the removal path in ``SchedulerService`` when a job is removed
        so that the durable ``removed`` state survives heap removal.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to mark as removed.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE scheduled_jobs SET removed_at = :removed_at WHERE id = :id",
            {"removed_at": time.time(), "id": db_id},
        )
        await db.commit()

    async def mark_job_status(
        self,
        db_id: int,
        status: ScheduleStatus,
        reason: ScheduleStatusReason | None,
        *,
        next_run: float | None,
        fire_at: float | None,
        jitter: float | None,
    ) -> None:
        """Persist a ``Job.transition_to()`` status change and the job's timing for the given row.

        Called after every schedule-status transition (scheduled, waiting, completed) so a
        degraded (DB-only) response still reflects the job's true status and next occurrence
        when live enrichment is unavailable. The timing columns are written in the same
        UPDATE as the status, so a non-``SCHEDULED`` transition clears them by passing
        ``None``. Does not touch ``removed_at`` — that is a separate lifecycle axis handled
        by ``mark_job_removed``.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to update.
            status: The new ``schedule_status``.
            reason: The new ``schedule_status_reason`` value, or ``None`` to clear it.
            next_run: Unjittered next fire time (epoch seconds), or ``None`` to clear it.
            fire_at: Actual dispatch time after jitter (epoch seconds), or ``None`` to clear it.
            jitter: Configured jitter upper bound (seconds), or ``None`` to clear it.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE scheduled_jobs SET schedule_status = :schedule_status, "
            "schedule_status_reason = :schedule_status_reason, "
            "next_run = :next_run, fire_at = :fire_at, jitter = :jitter WHERE id = :id",
            {
                "schedule_status": status,
                "schedule_status_reason": reason,
                "next_run": next_run,
                "fire_at": fire_at,
                "jitter": jitter,
                "id": db_id,
            },
        )
        await db.commit()

    async def clear_stale_job_timing(self, live_job_ids: list[int]) -> None:
        """Clear ``next_run``, ``fire_at`` and ``jitter`` on every scheduled_jobs row not in ``live_job_ids``.

        Args:
            live_job_ids: ``id`` of every job registered this session. Empty clears every row.
        """
        sql, params = build_clear_stale_job_timing_query(live_job_ids)
        db = self._db_service.db
        await db.execute(sql, params)
        await db.commit()

    async def mark_listener_cancelled(self, db_id: int) -> None:
        """Set ``removed_at`` to the current epoch time for the given listener row.

        Called from the cancel path in ``BusService`` when a listener is cancelled
        so that the durable ``removed`` state survives memory removal.

        This method intentionally keeps "cancelled" terminology (unlike its scheduler
        counterpart ``mark_job_removed``) because the Bus's public API still uses
        ``Subscription.cancel()``/removal, not ``Job.remove()``/``Scheduler.remove_job()`` —
        see design/specs/090-registered-manual-jobs/design.md's Key Constraints section.

        Args:
            db_id: The ``id`` of the ``listeners`` row to mark as removed.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE listeners SET removed_at = :removed_at WHERE id = :id",
            {"removed_at": time.time(), "id": db_id},
        )
        await db.commit()

    async def reconcile_registrations(
        self,
        app_key: str,
        live_listener_ids: list[int],
        live_job_ids: list[int],
        *,
        instance_name: str | None = None,
    ) -> None:
        """Reconcile listener and job registrations for an app after initialization.

        Every listener not in the live ID set gets ``retired_at`` set to the current time, ``once=True``
        or not. Listener rows are never deleted here: the near-miss recorder may still hold misses for a
        listener that hasn't flushed yet, so the database alone can't say whether it has history.
        Retention deletes a retired listener once its executions and misses age out, and
        ``SessionManager.cleanup_stale_once_listeners`` deletes a ``once=True`` listener that already ran.

        Jobs not in the live ID set are deleted when they have no execution history, and retired when
        they do.

        Args:
            app_key: The app key to reconcile.
            live_listener_ids: IDs of currently active listener rows.
            live_job_ids: IDs of currently active scheduled_job rows.
            instance_name: When provided, scopes every query to this instance so restarting one
                instance does not retire or delete sibling instances' rows. When None (default),
                reconciliation is app_key-scoped only.
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

            # Listeners are only ever retired here, never deleted: see the docstring.
            sql, params = build_retire_query(
                "listeners", app_key, live_listener_ids, now, only_with_history=False, instance_name=instance_name
            )
            await db.execute(sql, params)

            sql, params = build_delete_stale_jobs_query(app_key, live_job_ids, instance_name=instance_name)
            await db.execute(sql, params)

            sql, params = build_retire_query(
                "scheduled_jobs", app_key, live_job_ids, now, only_with_history=True, instance_name=instance_name
            )
            await db.execute(sql, params)

            await db.commit()
        except Exception:  # any failure rolls back, then re-raises to the caller
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
                    session_id, app_key, instance_name,
                    execution_id, tier, primitive, source_location,
                    stall_duration_ms, detected_ts, source_tier, reason, frames
                ) VALUES (
                    :session_id, :app_key, :instance_name,
                    :execution_id, :tier, :primitive, :source_location,
                    :stall_duration_ms, :detected_ts, :source_tier, :reason, :frames
                )
                """,
                {
                    "session_id": event.session_id,
                    "app_key": event.app_key,
                    "instance_name": event.instance_name,
                    "execution_id": event.execution_id,
                    "tier": event.tier,
                    "primitive": event.primitive,
                    "source_location": event.source_location,
                    "stall_duration_ms": event.stall_duration_ms,
                    "detected_ts": event.detected_ts,
                    "source_tier": event.source_tier,
                    "reason": event.reason,
                    "frames": encode_frames(event.frames),
                },
            )
            await db.commit()
        except STORAGE_ERRORS:
            LOGGER.warning(
                "Dropped blocking_events row (DB write failed) — tier=%s app=%s primitive=%s",
                event.tier,
                event.app_key,
                event.primitive,
                exc_info=True,
            )

    async def insert_api_write(self, row: "ApiWriteRow") -> None:
        """Insert a ``pending`` ``api_writes`` row for a write being sent.

        A DB write failure is logged with the write's identity and the row dropped; its later outcome
        update then matches nothing.
        """
        db = self._db_service.db
        try:
            await db.execute(
                """
                INSERT INTO api_writes (
                    write_id, session_id, app_key, instance_name, execution_id,
                    kind, operation, target, data, outcome, sent_ts
                ) VALUES (
                    :write_id, :session_id, :app_key, :instance_name, :execution_id,
                    :kind, :operation, :target, :data, 'pending', :sent_ts
                )
                """,
                {
                    "write_id": row.write_id,
                    "session_id": row.session_id,
                    "app_key": row.app_key,
                    "instance_name": row.instance_name,
                    "execution_id": row.execution_id,
                    "kind": row.kind,
                    "operation": row.operation,
                    "target": None if row.target is None else orjson.dumps(row.target).decode(),
                    "data": row.data,
                    "sent_ts": row.sent_ts,
                },
            )
            await db.commit()
        except STORAGE_ERRORS:
            LOGGER.warning(
                "Dropped api_writes row (DB write failed) — app=%s kind=%s write=%s",
                row.app_key,
                row.kind,
                row.write_id,
                exc_info=True,
            )

    async def update_api_write_outcome(
        self,
        write_id: str,
        *,
        outcome: "ApiWriteOutcome",
        context_id: str | None,
        error_code: str | None,
        error_message: str | None,
        resolved_ts: float | None,
    ) -> None:
        """Set a pending write row's outcome; a row that already has one keeps it (first outcome wins).

        A DB write failure is logged and the row left as it was.
        """
        db = self._db_service.db
        try:
            await db.execute(
                """
                UPDATE api_writes
                SET outcome = :outcome, context_id = :context_id, error_code = :error_code,
                    error_message = :error_message, resolved_ts = :resolved_ts
                WHERE write_id = :write_id AND outcome = 'pending'
                """,
                {
                    "write_id": write_id,
                    "outcome": outcome,
                    "context_id": context_id,
                    "error_code": error_code,
                    "error_message": error_message,
                    "resolved_ts": resolved_ts,
                },
            )
            await db.commit()
        except STORAGE_ERRORS:
            LOGGER.warning(
                "Dropped api_writes outcome update (DB write failed) — write=%s outcome=%s",
                write_id,
                outcome,
                exc_info=True,
            )

    async def upsert_listener_misses(self, rows: "list[ListenerMissRow]") -> None:
        """Add a batch of near-miss rollups to ``listener_misses``, merging into rows already stored for their key.

        On a key already stored (listener, hour, reason, filter), ``count`` adds, ``first_ts`` keeps the earlier
        time, and the last-event columns change only when this rollup's last event is at least as recent, so a
        restart or app reload within the hour adds to its row. A row whose listener has since been deleted is
        skipped rather than failing the batch on the foreign key. Any failure rolls the batch back and re-raises.
        """
        if not rows:
            return
        db = self._db_service.db
        try:
            await db.execute("BEGIN")
            await db.executemany(_LISTENER_MISS_UPSERT_SQL, [listener_miss_params(row) for row in rows])
            await db.commit()
        except Exception:  # any failure rolls back, then re-raises to the caller
            await db.rollback()
            raise

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
            params_list = [execution_insert_params(r) for r in records]
            await db.executemany(EXECUTION_INSERT_SQL, params_list)
            await db.commit()
        except Exception:  # any failure rolls back, then re-raises to the caller
            await db.rollback()
            raise

    async def persist_execution_batch_with_fk_fallback(self, records: list[ExecutionRecord]) -> list[ExecutionRecord]:
        """Insert execution records row-by-row with FK violation fallback (best-effort per record).

        Called by ``execution_pipeline.handle_fk_violation`` after a batch INSERT already
        failed with IntegrityError. Each record is inserted individually; on FK violation
        the FK field is nulled and retried. Runs as one ``submit()`` call on the DB write
        queue, avoiding N round-trips.

        Atomicity is best-effort per record: if an individual record fails even after FK
        nulling, it is silently dropped and remaining records are still committed.

        Returns the records that were dropped (failed even with null FK); every other record
        was committed.
        """
        db = self._db_service.db
        dropped: list[ExecutionRecord] = []

        if not records:
            return dropped

        try:
            await db.execute("BEGIN")

            for record in records:
                params = execution_insert_params(record)
                fk_field = "listener_id" if record.kind == "handler" else "job_id"
                if await insert_row_with_fk_fallback(db, params, fk_field, LOGGER):
                    dropped.append(record)

            await db.commit()
        except Exception:  # any failure rolls back, then re-raises to the caller
            await db.rollback()
            raise

        return dropped


def listener_miss_params(row: "ListenerMissRow") -> dict[str, object]:
    """The named SQL parameters of one ``listener_misses`` upsert row."""
    return {column: getattr(row, column) for column in _LISTENER_MISS_COLUMNS}
