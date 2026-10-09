"""Age-based retention cleanup for ``DatabaseService``, as a mixin."""

import time
import typing
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


class _RetentionBatchError(Exception):
    """Raised by ``_delete_target_batched()`` when a batch DELETE fails.

    Carries ``partial_deleted`` — the count of rows already committed by earlier batches for
    this target — so the caller can record real partial progress instead of a false zero. The
    stack frame holding the local accumulator is gone once this propagates, so the count has
    to ride out on the exception itself rather than a return value.

    ``partial_deleted`` is a lower bound, not necessarily exact: if the failure occurs during
    ``commit()`` itself (e.g. ``SQLITE_BUSY`` mid-fsync, or an ``OSError`` from a full disk), the
    current batch's rows are counted as not deleted even though the commit's actual outcome may
    be ambiguous. This is safe (age-based deletes are idempotent and a retry re-selects any rows
    not actually committed) but means the reported count can undercount when correlating with
    other operational symptoms.
    """

    def __init__(self, partial_deleted: int, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.partial_deleted = partial_deleted


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

    db: aiosqlite.Connection
    enqueue: "Callable[[Coroutine[Any, Any, Any]], bool]"

    async def run_retention_cleanup(self) -> bool:
        """Enqueue a retention cleanup; False if dropped (no database, or write queue full)."""
        if self._db is None or self._db_write_queue is None:
            return False
        return self.enqueue(self._do_run_retention_cleanup())

    async def _delete_target_batched(
        self, target: RetentionTarget, now: float, config: "HassetteConfig"
    ) -> tuple[int, bool]:
        """Batched age-based delete for one retention target.

        ``exhausted`` is True when the per-cycle batch cap ran out with rows matching the
        cutoff still present. This is a normal return, not an exception, but the caller must
        treat it the same as a raised failure for parent-guard gating purposes: an exhausted
        target's cutoff window still has known-stale rows, the exact condition the
        parent-guard's own NOT EXISTS check assumes can't happen for any target it isn't told
        about. The remainder is picked up on the next hourly cycle either way.

        Returns:
            tuple[int, bool]: ``(total_deleted, exhausted)``.

        Raises:
            _RetentionBatchError: On failure, carrying the count of rows already committed by
                earlier batches — the caller is responsible for recording failed_labels and
                preserving that partial progress from the exception.
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
                raise _RetentionBatchError(total_deleted, exc) from exc
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
                raise _RetentionBatchError(total_deleted, exc) from exc
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
        return total_deleted, exhausted

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

    async def _do_run_retention_cleanup(self) -> None:
        """Execute the retention DELETE queries; called by the write-queue worker.

        Iterates _RETENTION_TABLES for tier-aware, batched age-based deletes — each target
        gets its own per-batch transaction, bounding per-batch lock duration, and a failure
        on one target does not roll back deletes already committed for another.
        Parent-guard deletes for listeners/scheduled_jobs only run once every target has both
        succeeded AND fully cleared its cutoff window this cycle; a target that raised or hit
        the per-cycle batch cap (see ``_delete_target_batched``'s ``exhausted`` return) skips
        the guard for this cycle so it can never run against a state where an upstream delete
        is known to be incomplete. A parent-guard failure is rolled back, logged individually,
        and also folded into the "Retention cleanup summary" line below (as
        "parent-guard deletes failed") so it isn't only visible in a separate log line.
        """
        config = self.hassette.config
        now = time.time()
        deleted_by_label: dict[str, int] = {}
        failed_labels: set[str] = set()
        incomplete_labels: set[str] = set()

        for target in _RETENTION_TABLES:
            try:
                deleted, exhausted = await self._delete_target_batched(target, now, config)
            except _RetentionBatchError as exc:
                await safe_rollback(self.db, self, target.failsafe_label)
                self.logger.exception("Retention cleanup failed for %s", target.failsafe_label)
                # Batches already committed before the failure are real, durable progress —
                # record them alongside the failure rather than reporting a false zero.
                deleted_by_label[target.failsafe_label] = exc.partial_deleted
                failed_labels.add(target.failsafe_label)
                continue
            deleted_by_label[target.failsafe_label] = deleted
            if exhausted:
                incomplete_labels.add(target.failsafe_label)

        listeners_deleted = 0
        jobs_deleted = 0
        parent_guard_failed = False

        if not failed_labels and not incomplete_labels:
            try:
                # Use the standard retention window for parent-guard deletes.
                cutoff = now - (config.database.retention_days * SECONDS_PER_DAY)
                listeners_deleted, jobs_deleted = await self._run_parent_guard_deletes(cutoff)
            except Exception:
                await safe_rollback(self.db, self, "parent-guard deletes")
                self.logger.exception("Retention cleanup failed for parent-guard deletes")
                parent_guard_failed = True
        else:
            self.logger.warning(
                "Retention cleanup: skipping parent-guard deletes — target(s) %s",
                "; ".join(_target_failure_reasons(failed_labels, incomplete_labels)),
            )

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
