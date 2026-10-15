"""Age-based retention cleanup for ``DatabaseService``, as a mixin."""

import time
import typing
from dataclasses import dataclass
from typing import Any

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_sql import CLEANUP_PROGRESS_LOG_INTERVAL, SQL_BEGIN, reclaim_free_pages, safe_rollback
from hassette.core.retention_targets import _RETENTION_TABLES, RetentionTarget, build_age_where
from hassette.core.telemetry.reconcile_sql import (
    build_prune_removed_app_manifests_query,
    build_retire_removed_apps_query,
)

if typing.TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Coroutine

    from hassette import Hassette
    from hassette.config.config import HassetteConfig

REMOVED_APP_MANIFESTS_LABEL = "removed app manifests"
"""Label for pruned ``app_manifests`` rows in the "Retention cleanup summary" line."""

SESSIONS_LABEL = "sessions"
"""Label for deleted ``sessions`` rows in the "Retention cleanup summary" line."""

PARENT_GUARD_SKIP_ESCALATION_CYCLES = 3
"""Consecutive retention cycles with parent-guard deletes skipped before the skip is logged as
an ERROR instead of a WARNING — separates a transient one-off target failure from a target that
is chronically blocking retired listener/scheduled_job cleanup."""


@dataclass(frozen=True, slots=True)
class TargetDeleteResult:
    """Outcome of ``_delete_target_batched()`` for one retention target.

    ``exhausted`` and ``error`` never both hold: a failure returns before the exhaustion check.
    """

    deleted: int
    """Rows committed by this target's batches this cycle.

    On failure this is the progress made before the failing batch, and is a lower bound: if the
    failure occurs during ``commit()`` itself (e.g. ``SQLITE_BUSY`` mid-fsync, or an ``OSError``
    from a full disk), the current batch's rows are counted as not deleted even though the
    commit's actual outcome may be ambiguous. This is safe (age-based deletes are idempotent and a
    retry re-selects any rows not actually committed) but the reported count can undercount when
    correlating with other operational symptoms.
    """

    exhausted: bool = False
    """The per-cycle batch cap ran out with rows matching the cutoff still present."""

    error: Exception | None = None
    """The exception that aborted the target's deletes, or None if it completed."""


async def _execute_target_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    cutoff: float,
    batch_limit: int,
) -> int:
    """Delete up to ``batch_limit`` rows in ``target.table`` older than ``cutoff``, filtered by
    ``target.source_tier`` when set, for age-based retention cleanup.

    Does not manage transactions -- the caller owns BEGIN/commit/rollback.
    """
    where, params = build_age_where(target, cutoff)
    cursor = await db.execute(
        f"DELETE FROM {target.table} WHERE id IN (SELECT id FROM {target.table} WHERE {where} LIMIT ?)",
        [*params, batch_limit],
    )
    return cursor.rowcount or 0


def _target_failure_reasons(failed_labels: set[str], incomplete_labels: set[str]) -> list[str]:
    """Format a retention-cleanup cycle's failed/incomplete targets for a log message.

    Shared by the parent-guard skip warning and the cycle summary log in
    ``_do_run_retention_cleanup()`` — both need the same "failed: X; incomplete: Y" phrasing.
    """
    reasons: list[str] = []
    if failed_labels:
        reasons.append(f"failed: {', '.join(sorted(failed_labels))}")
    if incomplete_labels:
        reasons.append(f"incomplete: {', '.join(sorted(incomplete_labels))}")
    return reasons


@dataclass(frozen=True, slots=True)
class ParentGuardResult:
    """Outcome of ``_run_parent_guard_deletes()``: rows retired and deleted, and manifests pruned."""

    listeners_retired: int = 0
    jobs_retired: int = 0
    retired_app_keys: tuple[str, ...] = ()
    listeners_deleted: int = 0
    jobs_deleted: int = 0
    pruned_manifest_keys: tuple[str, ...] = ()
    sessions_deleted: int = 0


class DatabaseRetentionMixin:
    """Retention-cleanup methods of ``DatabaseService``; reads the host attributes declared below."""

    hassette: "Hassette"
    logger: "logging.Logger"
    _consecutive_parent_guard_skips: int

    db: aiosqlite.Connection
    enqueue_if_ready: "Callable[[Callable[[], Coroutine[Any, Any, Any]]], bool]"

    async def run_retention_cleanup(self) -> bool:
        """Enqueue a retention cleanup; False if dropped (no database, or write queue full)."""
        return self.enqueue_if_ready(self._do_run_retention_cleanup)

    async def _delete_target_batched(
        self, target: RetentionTarget, now: float, config: "HassetteConfig"
    ) -> TargetDeleteResult:
        """Batched age-based delete for one retention target.

        A DB error from a batch or the stale-row probe is returned in ``error`` rather than
        raised, alongside the rows earlier batches already committed. The caller owns rolling
        back the failed batch's transaction and logging the error.

        ``exhausted`` is set when the per-cycle batch cap ran out with rows matching the cutoff
        still present. The caller must treat it the same as a failure for parent-guard gating
        purposes: an exhausted target's cutoff window still has known-stale rows, the exact
        condition the parent-guard's own NOT EXISTS check assumes can't happen for any target it
        isn't told about. The remainder is picked up on the next hourly cycle either way.
        """
        target_start = time.monotonic()
        cutoff = now - (target.retention_days_getter(config) * SECONDS_PER_DAY)
        batch_size = config.database.retention_delete_batch
        max_batches = config.database.retention_max_batches_per_target

        total_deleted = 0
        exhausted = False
        for batch_number in range(1, max_batches + 1):
            try:
                await self.db.execute(SQL_BEGIN)
                batch_count = await _execute_target_delete(self.db, target, cutoff=cutoff, batch_limit=batch_size)
                await self.db.commit()
            except Exception as exc:
                return TargetDeleteResult(total_deleted, error=exc)
            total_deleted += batch_count
            if batch_count < batch_size:
                break
            if batch_number % CLEANUP_PROGRESS_LOG_INTERVAL == 0:
                self.logger.info(
                    "Retention cleanup in progress: %s — %d deleted across %d batches so far",
                    target.failsafe_label,
                    total_deleted,
                    batch_number,
                )
        else:
            # Every batch ran full-sized, but that doesn't prove rows past the cutoff remain —
            # the final full batch may have removed the last one. Check before declaring the
            # target incomplete; an unnecessary "incomplete" here skips otherwise-safe
            # parent-guard cleanup and emits a false backlog warning for the next hour.
            where, params = build_age_where(target, cutoff)
            try:
                stale_cursor = await self.db.execute(f"SELECT 1 FROM {target.table} WHERE {where} LIMIT 1", params)
                stale_row = await stale_cursor.fetchone()
            except Exception as exc:
                return TargetDeleteResult(total_deleted, error=exc)
            if stale_row is not None:
                exhausted = True
                self.logger.warning(
                    "Retention cleanup: %s hit the %d-batch cap for this cycle with records still past "
                    "cutoff — treating as incomplete and skipping parent-guard deletes this cycle; "
                    "remainder continues next cycle",
                    target.failsafe_label,
                    max_batches,
                )

        elapsed = time.monotonic() - target_start
        if total_deleted > 0:
            self.logger.info(
                "Retention cleanup: deleted %d %s in %.1fs",
                total_deleted,
                target.failsafe_label,
                elapsed,
            )
        return TargetDeleteResult(total_deleted, exhausted=exhausted)

    def live_app_keys(self) -> list[str]:
        """Return every app key retention must treat as present: in the current config, or running.

        Config alone is not enough: a hot reload installs the new config before it stops the
        apps it removed, so an app about to be stopped would look removed. The registry covers
        an app until its stop begins (``stop_app`` unregisters before shutting down), so rows of
        an app that is still shutting down can be retired; that is harmless, because retiring
        deletes nothing and re-registration clears it. Read fresh on every cycle, so nothing
        about an app's removal is stored and a failed cycle simply retries on the next one.

        Config and ``registry.manifests`` hold the same apps: ``refresh_config()`` updates both
        with no ``await`` between, and this runs on the DB write-queue task.
        """
        keys = set(self.hassette.config.apps.manifests)
        try:
            app_handler = self.hassette.app_handler
        except RuntimeError:
            # The accessor raises only when no AppHandler is wired (an embedding without one,
            # e.g. a test harness); no app can be running there, so the config keys are complete.
            self.logger.debug("AppHandler not wired; treating config apps as the live set")
        else:
            keys.update(app_handler.registry.app_keys())
        return sorted(keys)

    async def _run_parent_guard_deletes(
        self, cutoff: float, now: float, live_app_keys: list[str], current_session_id: int | None
    ) -> ParentGuardResult:
        """Retire removed apps' registrations, run the NOT EXISTS-guarded deletes, then prune manifests.

        "Parent-guard" names the whole second phase of a cleanup cycle; all of it runs in one
        transaction:

        1. Retire unretired app-tier listener/scheduled_job rows of apps not in
           ``live_app_keys`` (``build_retire_removed_apps_query``). Removed apps are never
           reconciled again, so without this their rows would never age out. Rows are retired
           rather than deleted, so an execution still waiting in the write queue keeps a valid
           parent.
        2. Delete retired listeners/scheduled_jobs only once ALL their child executions have
           also aged out. This prevents orphaning recent executions whose parent row would be
           deleted because retired_at (set at restart time) diverges from last execution time.
           Rows retired in step 1 this cycle are not past the cutoff yet.
        3. Delete ``app_manifests`` rows of apps not in ``live_app_keys`` that nothing references
           anymore (``build_prune_removed_app_manifests_query``).
        4. Delete ``sessions`` rows that stopped before the cutoff, are not the current session, and
           are no longer referenced by any ``executions`` or ``blocking_events`` row. Sessions
           still referenced wait until those rows age out under their own tier's window. A
           session with ``stopped_at IS NULL`` (the live one, or a previous run's orphan not yet
           backfilled by ``mark_orphaned_sessions``) is never deleted. The size failsafe does not
           reclaim sessions: they are small, and only age-based retention removes them.

        Args:
            cutoff: Retention cutoff for step 2's and step 4's deletes.
            now: Timestamp step 1 stamps into ``retired_at``.
            live_app_keys: App keys to leave alone (see ``live_app_keys()``).
            current_session_id: The live session's id, never deleted; None if no session exists yet.

        Returns:
            ParentGuardResult: Rows retired and deleted, and the app keys retired and pruned.

        Raises:
            Exception: Propagates any DB error from the statements.
        """
        await self.db.execute(SQL_BEGIN)
        retired_listener_cursor = await self.db.execute(
            *build_retire_removed_apps_query("listeners", live_app_keys, now)
        )
        retired_listener_keys = [row[0] for row in await retired_listener_cursor.fetchall()]
        retired_job_cursor = await self.db.execute(
            *build_retire_removed_apps_query("scheduled_jobs", live_app_keys, now)
        )
        retired_job_keys = [row[0] for row in await retired_job_cursor.fetchall()]
        deleted_listener_cursor = await self.db.execute(
            """
            DELETE FROM listeners
            WHERE retired_at IS NOT NULL AND retired_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM executions
                  WHERE listener_id = listeners.id
                    AND execution_start_ts >= ?
              )
            """,
            (cutoff, cutoff),
        )
        # Same guard for scheduled_jobs.
        deleted_job_cursor = await self.db.execute(
            """
            DELETE FROM scheduled_jobs
            WHERE retired_at IS NOT NULL AND retired_at < ?
              AND NOT EXISTS (
                  SELECT 1 FROM executions
                  WHERE job_id = scheduled_jobs.id
                    AND execution_start_ts >= ?
              )
            """,
            (cutoff, cutoff),
        )
        pruned_manifest_cursor = await self.db.execute(*build_prune_removed_app_manifests_query(live_app_keys))
        pruned_manifest_keys = tuple(sorted(row[0] for row in await pruned_manifest_cursor.fetchall()))
        deleted_session_cursor = await self.db.execute(
            """
            DELETE FROM sessions
            WHERE stopped_at IS NOT NULL AND stopped_at < ?
              AND id IS NOT ?
              AND NOT EXISTS (SELECT 1 FROM executions WHERE session_id = sessions.id)
              AND NOT EXISTS (SELECT 1 FROM blocking_events WHERE session_id = sessions.id)
            """,
            (cutoff, current_session_id),
        )
        await self.db.commit()
        return ParentGuardResult(
            listeners_retired=len(retired_listener_keys),
            jobs_retired=len(retired_job_keys),
            retired_app_keys=tuple(sorted(set(retired_listener_keys) | set(retired_job_keys))),
            listeners_deleted=deleted_listener_cursor.rowcount or 0,
            jobs_deleted=deleted_job_cursor.rowcount or 0,
            pruned_manifest_keys=pruned_manifest_keys,
            sessions_deleted=deleted_session_cursor.rowcount or 0,
        )

    def _record_parent_guard_skip(self, failed_labels: set[str], incomplete_labels: set[str]) -> None:
        """Count a skipped parent-guard cycle and log it, escalating a sustained streak to ERROR.

        The skip is a WARNING naming the streak length until it reaches
        ``PARENT_GUARD_SKIP_ESCALATION_CYCLES``, then an ERROR, so a chronically failing target is
        distinguishable from a one-off. Unlike the size-failsafe counters, which only ever warn,
        this streak escalates: while it lasts, retired listener/scheduled_job rows are never pruned.
        """
        self._consecutive_parent_guard_skips += 1
        streak = self._consecutive_parent_guard_skips
        reasons = "; ".join(_target_failure_reasons(failed_labels, incomplete_labels))
        if streak >= PARENT_GUARD_SKIP_ESCALATION_CYCLES:
            self.logger.error(
                "Retention cleanup: skipping parent-guard deletes (%d consecutive cycles) — retired "
                "listeners/scheduled_jobs are not being pruned; target(s) %s",
                streak,
                reasons,
            )
            return
        self.logger.warning(
            "Retention cleanup: skipping parent-guard deletes (%d consecutive cycle(s)) — target(s) %s",
            streak,
            reasons,
        )

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker or the startup catch-up.

        Iterates _RETENTION_TABLES for tier-aware, batched age-based deletes — each target
        gets its own per-batch transaction, bounding per-batch lock duration, and a failure
        on one target does not roll back deletes already committed for another.
        Parent-guard deletes for listeners/scheduled_jobs only run once every target has both
        succeeded AND fully cleared its cutoff window this cycle; a target that failed or hit
        the per-cycle batch cap (see ``_delete_target_batched``'s ``exhausted`` return) skips
        the guard for this cycle so it can never run against a state where an upstream delete
        is known to be incomplete. The same gate covers pruning ``app_manifests`` rows for apps
        removed from config and deleting old unreferenced ``sessions`` rows, both of which run
        inside the parent-guard transaction. A parent-guard failure is rolled back, logged
        individually, and also folded into the "Retention cleanup summary" line below (as
        "parent-guard deletes failed") so it isn't only visible in a separate log line. Removed-app
        and session cleanup therefore advance only on cycles where the parent-guard runs; a
        sustained skip streak (see below) stalls them too.

        Skipped cycles are counted by ``_record_parent_guard_skip``; the counter resets whenever
        the parent-guard actually runs, whether or not it succeeds. The cycle ends by reclaiming the
        pages its deletes freed (``_reclaim_freed_pages``).
        """
        config = self.hassette.config
        now = time.time()
        deleted_by_label: dict[str, int] = {}
        failed_labels: set[str] = set()
        incomplete_labels: set[str] = set()

        for target in _RETENTION_TABLES:
            result = await self._delete_target_batched(target, now, config)
            # Recorded on success and failure alike: a failed target's earlier committed batches are
            # real, durable progress, so report them rather than a false zero.
            deleted_by_label[target.failsafe_label] = result.deleted
            if result.error is not None:
                await safe_rollback(self.db, self, target.failsafe_label)
                self.logger.error("Retention cleanup failed for %s", target.failsafe_label, exc_info=result.error)
                failed_labels.add(target.failsafe_label)
                continue
            if result.exhausted:
                incomplete_labels.add(target.failsafe_label)

        guard = ParentGuardResult()
        parent_guard_failed = False

        if not failed_labels and not incomplete_labels:
            self._consecutive_parent_guard_skips = 0
            try:
                # Use the standard retention window for parent-guard deletes.
                cutoff = now - (config.database.retention_days * SECONDS_PER_DAY)
                guard = await self._run_parent_guard_deletes(
                    cutoff, now, self.live_app_keys(), self.hassette.try_session_id()
                )
            # Not BaseException: every cancellation path today either rolls back itself (the
            # startup catch-up timeout) or closes the connection (shutdown), which rolls back.
            except Exception:
                await safe_rollback(self.db, self, "parent-guard deletes")
                self.logger.exception("Retention cleanup failed for parent-guard deletes")
                parent_guard_failed = True
        else:
            self._record_parent_guard_skip(failed_labels, incomplete_labels)

        deleted_by_label[REMOVED_APP_MANIFESTS_LABEL] = len(guard.pruned_manifest_keys)
        deleted_by_label[SESSIONS_LABEL] = guard.sessions_deleted
        deleted_summary = {label: count for label, count in deleted_by_label.items() if count > 0}
        if deleted_summary or failed_labels or incomplete_labels or parent_guard_failed:
            parts = ", ".join(f"{count} {label}" for label, count in deleted_summary.items())
            tags = _target_failure_reasons(failed_labels, incomplete_labels)
            if parent_guard_failed:
                tags.append("parent-guard deletes failed")
            self.logger.info(
                "Retention cleanup summary: deleted %s%s",
                parts or "nothing",
                f" ({'; '.join(tags)})" if tags else "",
            )
        if guard.retired_app_keys:
            self.logger.info(
                "Retention cleanup: retired %d listeners, %d scheduled_jobs of apps no longer in config: %s",
                guard.listeners_retired,
                guard.jobs_retired,
                ", ".join(guard.retired_app_keys),
            )
        if guard.listeners_deleted or guard.jobs_deleted:
            self.logger.info(
                "Retention cleanup: deleted %d retired listeners, %d retired scheduled_jobs",
                guard.listeners_deleted,
                guard.jobs_deleted,
            )
        if guard.pruned_manifest_keys:
            self.logger.info(
                "Retention cleanup: removed manifests for apps no longer in config with no remaining telemetry: %s",
                ", ".join(guard.pruned_manifest_keys),
            )

        await self._reclaim_freed_pages()

    async def _reclaim_freed_pages(self) -> None:
        """Return the pages this cycle's deletes freed, so the free list can't grow without bound.

        Routine maintenance: the free list otherwise keeps the file larger than its live data
        indefinitely. The size failsafe measures live data only, so this has no effect on its
        decisions. Any remainder past the time budget is picked up by the next cycle. No
        checkpoint here: SQLite's auto-checkpoint covers the WAL.
        """
        try:
            reclaim = await reclaim_free_pages(self.db)
        except Exception:
            self.logger.exception("Retention cleanup: free-page reclaim failed")
            return
        if reclaim.reclaimed > 0:
            self.logger.info(
                "Retention cleanup: reclaimed %d free pages (%d remaining)", reclaim.reclaimed, reclaim.remaining
            )
