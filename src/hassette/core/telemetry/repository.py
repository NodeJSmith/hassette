"""TelemetryRepository: encapsulates all SQL writes for CommandExecutor telemetry."""

import time
from logging import getLogger
from typing import TYPE_CHECKING

from hassette.config.classes import AppManifest
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry.insert_params import (
    _EXECUTION_INSERT_SQL,
    _insert_row_with_fk_fallback,
    execution_insert_params,
    job_insert_params,
    listener_insert_params,
    manifest_insert_params,
)
from hassette.core.telemetry.reconcile_sql import _build_delete_query, _build_retire_query, _instance_index_clause
from hassette.schemas.log_models import BlockingEvent
from hassette.types.types import is_framework_key

LOGGER = getLogger(__name__)

if TYPE_CHECKING:
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
                "group", mode,
                predicate_description, human_description,
                schedule_status, schedule_status_reason
            ) VALUES (
                :app_key, :instance_index, :job_name, :handler_method,
                :trigger_type,
                :trigger_label, :trigger_detail,
                :repeat,
                :args_json, :kwargs_json,
                :source_location, :registration_source, :source_tier,
                :group, :mode,
                :predicate_description, :human_description,
                :schedule_status, :schedule_status_reason
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
                mode = excluded.mode,
                predicate_description = excluded.predicate_description,
                human_description = excluded.human_description,
                schedule_status = excluded.schedule_status,
                schedule_status_reason = excluded.schedule_status_reason,
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
                app_key, class_name, display_name, filename, enabled, autostart, auto_loaded
            ) VALUES (
                :app_key, :class_name, :display_name, :filename, :enabled, :autostart, :auto_loaded
            )
            ON CONFLICT(app_key)
            DO UPDATE SET
                class_name = excluded.class_name,
                display_name = excluded.display_name,
                filename = excluded.filename,
                enabled = excluded.enabled,
                autostart = excluded.autostart,
                auto_loaded = excluded.auto_loaded,
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

    async def mark_job_status(self, db_id: int, status: str, reason: str | None) -> None:
        """Persist a ``Job.transition_to()`` status change for the given job row.

        Called after every schedule-status transition (scheduled, waiting, completed) so a
        degraded (DB-only) response still reflects the job's true status when live
        enrichment is unavailable. Does not touch ``removed_at`` — that is a separate
        lifecycle axis handled by ``mark_job_removed``.

        Args:
            db_id: The ``id`` of the ``scheduled_jobs`` row to update.
            status: The new ``schedule_status`` value (a ``ScheduleStatus.value``).
            reason: The new ``schedule_status_reason`` value, or ``None`` to clear it.
        """
        db = self._db_service.db
        await db.execute(
            "UPDATE scheduled_jobs SET schedule_status = :schedule_status, "
            "schedule_status_reason = :schedule_status_reason WHERE id = :id",
            {"schedule_status": status, "schedule_status_reason": reason, "id": db_id},
        )
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
        session_id: int | None = None,
        instance_index: int | None = None,
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
            instance_index: When provided, scopes all five SQL paths (both listener queries,
                the once=True cleanup block, and both scheduled_jobs queries) to this instance
                so restarting one instance does not delete or retire sibling instances' rows.
                When None (default), reconciliation is app_key-scoped only — unchanged behavior.
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
                instance_index=instance_index,
            )
            await db.execute(sql, params)

            sql, params = _build_retire_query(
                "listeners",
                app_key,
                live_listener_ids,
                "listener_id",
                now,
                extra_where=" AND once = 0",
                instance_index=instance_index,
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
                instance_clause, instance_params = _instance_index_clause(instance_index)
                params_once.update(instance_params)
                await db.execute(
                    f"""
                    DELETE FROM listeners
                    WHERE app_key = :app_key AND once = 1
                      AND source_tier = :source_tier{instance_clause}
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
                instance_index=instance_index,
            )
            await db.execute(sql, params)

            sql, params = _build_retire_query(
                "scheduled_jobs",
                app_key,
                live_job_ids,
                "job_id",
                now,
                instance_index=instance_index,
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
            params_list = [execution_insert_params(r) for r in records]
            await db.executemany(_EXECUTION_INSERT_SQL, params_list)
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def persist_execution_batch_with_fk_fallback(self, records: list[ExecutionRecord]) -> int:
        """Insert execution records row-by-row with FK violation fallback (best-effort per record).

        Called by ``execution_pipeline.handle_fk_violation`` after a batch INSERT already
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
                params = execution_insert_params(record)
                fk_field = "listener_id" if record.kind == "handler" else "job_id"
                if await _insert_row_with_fk_fallback(db, params, fk_field, LOGGER):
                    dropped += 1

            await db.commit()
        except Exception:
            await db.rollback()
            raise

        return dropped
