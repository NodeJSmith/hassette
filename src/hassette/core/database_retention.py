"""Age-based retention cleanup for ``DatabaseService``, as a mixin."""

import time
import typing
from dataclasses import dataclass
from typing import Any

import aiosqlite

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_sql import SQL_BEGIN, safe_rollback
from hassette.core.retention_targets import _RETENTION_TABLES, RetentionTarget, build_age_where

if typing.TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Callable, Coroutine

    from hassette import Hassette
    from hassette.config.config import HassetteConfig
    from hassette.core.database_write_queue import _WriteQueueItem

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


class DatabaseRetentionMixin:
    """Retention-cleanup methods of ``DatabaseService``; reads the host attributes declared below."""

    hassette: "Hassette"
    logger: "logging.Logger"
    _db: aiosqlite.Connection | None
    _db_write_queue: "asyncio.Queue[_WriteQueueItem] | None"
    _consecutive_parent_guard_skips: int

    db: aiosqlite.Connection
    enqueue: "Callable[[Coroutine[Any, Any, Any]], bool]"

    async def run_retention_cleanup(self) -> bool:
        """Enqueue a retention cleanup; False if dropped (no database, or write queue full)."""
        if self._db is None or self._db_write_queue is None:
            return False
        return self.enqueue(self._do_run_retention_cleanup())

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
        for _ in range(max_batches):
            try:
                await self.db.execute(SQL_BEGIN)
                batch_count = await _execute_target_delete(self.db, target, cutoff=cutoff, batch_limit=batch_size)
                await self.db.commit()
            except Exception as exc:
                return TargetDeleteResult(total_deleted, error=exc)
            total_deleted += batch_count
            if batch_count < batch_size:
                break
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

    async def _run_parent_guard_deletes(self, cutoff: float) -> tuple[int, int]:
        """NOT EXISTS-guarded deletes for retired listeners/scheduled_jobs.

        Only delete retired listeners/scheduled_jobs when ALL their child executions have
        also aged out. This prevents orphaning recent executions whose parent row would be
        deleted because retired_at (set at restart time) diverges from last execution time.

        Returns:
            tuple[int, int]: ``(listeners_deleted, jobs_deleted)``.

        Raises:
            Exception: Propagates any DB error from the delete statements.
        """
        await self.db.execute(SQL_BEGIN)
        cursor_rl = await self.db.execute(
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
        cursor_rj = await self.db.execute(
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
        await self.db.commit()
        return cursor_rl.rowcount or 0, cursor_rj.rowcount or 0

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
        """Execute the retention DELETE queries; called by the write-queue worker.

        Iterates _RETENTION_TABLES for tier-aware, batched age-based deletes — each target
        gets its own per-batch transaction, bounding per-batch lock duration, and a failure
        on one target does not roll back deletes already committed for another.
        Parent-guard deletes for listeners/scheduled_jobs only run once every target has both
        succeeded AND fully cleared its cutoff window this cycle; a target that failed or hit
        the per-cycle batch cap (see ``_delete_target_batched``'s ``exhausted`` return) skips
        the guard for this cycle so it can never run against a state where an upstream delete
        is known to be incomplete. A parent-guard failure is rolled back, logged individually,
        and also folded into the "Retention cleanup summary" line below (as
        "parent-guard deletes failed") so it isn't only visible in a separate log line.

        Skipped cycles are counted by ``_record_parent_guard_skip``; the counter resets whenever
        the parent-guard actually runs, whether or not it succeeds.
        """
        config = self.hassette.config
        now = time.time()
        deleted_by_label: dict[str, int] = {}
        failed_labels: set[str] = set()
        incomplete_labels: set[str] = set()

        for target in _RETENTION_TABLES:
            result = await self._delete_target_batched(target, now, config)
            # On failure, batches committed before it are real, durable progress — record them
            # alongside the failure rather than reporting a false zero.
            deleted_by_label[target.failsafe_label] = result.deleted
            if result.error is not None:
                await safe_rollback(self.db, self, target.failsafe_label)
                self.logger.error("Retention cleanup failed for %s", target.failsafe_label, exc_info=result.error)
                failed_labels.add(target.failsafe_label)
                continue
            if result.exhausted:
                incomplete_labels.add(target.failsafe_label)

        listeners_deleted = 0
        jobs_deleted = 0
        parent_guard_failed = False

        if not failed_labels and not incomplete_labels:
            self._consecutive_parent_guard_skips = 0
            try:
                # Use the standard retention window for parent-guard deletes.
                cutoff = now - (config.database.retention_days * SECONDS_PER_DAY)
                listeners_deleted, jobs_deleted = await self._run_parent_guard_deletes(cutoff)
            except Exception:
                await safe_rollback(self.db, self, "parent-guard deletes")
                self.logger.exception("Retention cleanup failed for parent-guard deletes")
                parent_guard_failed = True
        else:
            self._record_parent_guard_skip(failed_labels, incomplete_labels)

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
        if listeners_deleted or jobs_deleted:
            self.logger.info(
                "Retention cleanup: deleted %d retired listeners, %d retired scheduled_jobs",
                listeners_deleted,
                jobs_deleted,
            )
