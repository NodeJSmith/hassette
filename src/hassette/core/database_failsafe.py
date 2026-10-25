"""Size-limit failsafe for ``DatabaseService``, as a mixin."""

import sqlite3
import typing
from typing import Any

import aiosqlite

from hassette.core.database_sql import (
    CLEANUP_PROGRESS_LOG_INTERVAL,
    get_live_data_mb,
    reclaim_free_pages,
)
from hassette.core.retention_targets import _FAILSAFE_TABLES, RetentionTarget, build_tier_where
from hassette.core.telemetry.helpers import STORAGE_ERRORS
from hassette.utils.aiosqlite_utils import CHECKPOINT_TRUNCATE_SQL, checkpoint_blocked

if typing.TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Coroutine

    from hassette import Hassette


async def _execute_failsafe_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    batch_limit: int,
) -> int:
    """Delete the oldest ``batch_limit`` rows in ``target.table`` for the size failsafe.

    Rows are filtered by ``target.source_tier`` when set.

    Each statement autocommits (the write connection is ``isolation_level=None``), so there is no
    transaction to commit.
    """
    where_clause, params = build_tier_where(target)
    cursor = await db.execute(
        f"DELETE FROM {target.table} WHERE id IN "
        f"(SELECT id FROM {target.table} {where_clause}ORDER BY {target.timestamp_col} ASC LIMIT ?)",
        [*params, batch_limit],
    )
    return cursor.rowcount or 0


class WalCheckpointBlockedError(sqlite3.OperationalError):
    """``wal_checkpoint(TRUNCATE)`` was blocked by a reader or writer (SQLITE_BUSY)."""


async def truncate_wal(db: aiosqlite.Connection) -> None:
    """Run ``PRAGMA wal_checkpoint(TRUNCATE)``, raising if it was blocked.

    A blocked checkpoint doesn't raise on its own (see ``checkpoint_blocked()``), so this raises
    ``WalCheckpointBlockedError`` for it, letting callers treat it like any other failure.
    """
    cursor = await db.execute(CHECKPOINT_TRUNCATE_SQL)
    row = await cursor.fetchone()
    await cursor.close()
    if checkpoint_blocked(row):
        raise WalCheckpointBlockedError(f"wal_checkpoint(TRUNCATE) busy or failed: {row}")


class DatabaseSizeFailsafeMixin:
    """Size-failsafe methods of ``DatabaseService``; reads the host attributes declared below."""

    hassette: "Hassette"
    logger: "logging.Logger"
    _consecutive_size_triggers: int
    _consecutive_exhaustion_triggers: int
    _write_progress_count: int
    db: aiosqlite.Connection
    enqueue_if_ready: "Callable[[Callable[[], Coroutine[Any, Any, Any]]], bool]"

    async def get_live_data_size_mb(self) -> float:
        """Return the size of the database's in-use pages in megabytes -- the size the failsafe limits.

        Also the seam the failsafe tests patch to script the size the failsafe sees.
        """
        return await get_live_data_mb(self.db)

    async def read_live_data_mb_or_none(self) -> float | None:
        """Return ``get_live_data_size_mb()``, or None (logged) if reading it failed."""
        try:
            return await self.get_live_data_size_mb()
        except STORAGE_ERRORS:
            self.logger.exception("Size failsafe: reading live data size failed")
            return None

    async def shrink_database_file(self) -> None:
        """Best-effort: return free pages to the filesystem and truncate the WAL after rows were deleted.

        Deleting rows only moves their pages to the free list. Reclaiming them shrinks the file only
        on an ``auto_vacuum = INCREMENTAL`` database (every database the current migration runner
        creates); old ``auto_vacuum = NONE`` files keep their free pages on disk, which is fine
        because the limit is on live data. Unlike the cache's ``clear()``, this doesn't use a full
        ``VACUUM``: that rewrites the whole telemetry database while holding the write queue.

        Each step is isolated and its outcome never feeds back into the failsafe's decision. A
        blocked WAL checkpoint (a long-lived reader) is expected and logged without a traceback.
        """
        try:
            reclaim = await reclaim_free_pages(self.db)
        except STORAGE_ERRORS:
            self.logger.exception("Size failsafe: free-page reclaim failed after deleting rows")
        else:
            if reclaim.reclaimed > 0:
                self.logger.info(
                    "Size failsafe: reclaimed %d free pages (%d remaining)", reclaim.reclaimed, reclaim.remaining
                )
        try:
            await truncate_wal(self.db)
        except WalCheckpointBlockedError:
            self.logger.warning(
                "Size failsafe: WAL checkpoint blocked after deleting rows; the WAL stays until next time"
            )
        except STORAGE_ERRORS:
            self.logger.exception("Size failsafe: WAL checkpoint failed after deleting rows")

    async def _check_size_failsafe(self) -> None:
        """Delete oldest records while live data exceeds the configured size limit.

        Every size decision uses live data (in-use pages, see ``get_live_data_size_mb()``), which
        drops as soon as a DELETE commits. Free pages and the WAL are not counted, so a database
        that is oversized on disk only because of them loses no rows, whatever its ``auto_vacuum``
        mode. After a cycle that deleted rows, ``shrink_database_file()`` reclaims the free pages
        and truncates the WAL on a best-effort basis; its outcome never affects the decision.

        Iterates _FAILSAFE_TABLES grouped by priority (lower priority number = deleted
        first) -- targets marked ``failsafe_exempt`` are never touched here, no matter how far
        over the limit the database is. Within each priority tier, all tables in the group are
        deleted together per iteration; a target's ``source_tier`` filter (when set) is applied
        inside the inner SELECT so each tier's own oldest-N rows are deleted, not the
        globally-oldest N rows filtered down afterward. The process stops as soon as live data
        falls within the limit.

        ``max_iterations`` is a single budget shared across the whole run, not a per-tier
        allowance -- each tier only gets whatever iterations remain after higher-priority
        tiers have spent theirs. The budget is spent only by a batch that actually deletes rows,
        so an always-empty higher-priority tier can't starve lower-priority tiers of budget.

        If a tier's iteration loop runs out of its share of the budget without naturally draining,
        the tier is only treated as capped after probing whether it still has matching rows (an
        exact-boundary final batch can drain the tier while the database stays oversized purely
        because of lower-priority tiers). When the probe confirms rows remain, the run stops
        instead of advancing to a lower-priority tier, so app-tier data isn't deleted while a
        higher-priority backlog remains. The next hourly cycle retries the capped tier first.

        A DELETE failure on one priority tier is logged with the target's ``failsafe_label``,
        live data size, and limit, then skipped -- subsequent, lower-priority tiers still run. The
        failed tier retries on the next hourly cycle. A stale-row probe failure is isolated the
        same way. A failed live-size read inside the tier loop is logged and ends the run, marked
        incomplete.

        ``_consecutive_exhaustion_triggers`` is only incremented when every tier genuinely
        drained (no capped tier, no DELETE failure) and live data is still over the limit. A
        cycle that stopped early on a capped tier or skipped a tier after a failure resets it to
        0, so a later genuinely-exhausted cycle reports a fresh streak. A WARNING is logged for
        every over-limit cycle, naming every cause that applied.
        """
        config = self.hassette.config.database
        max_size_mb = config.max_size_mb
        if max_size_mb == 0:
            return

        live_mb = await self.get_live_data_size_mb()
        if live_mb <= max_size_mb:
            self._consecutive_size_triggers = 0
            self._consecutive_exhaustion_triggers = 0
            return

        self._consecutive_size_triggers += 1
        if self._consecutive_size_triggers > 1:
            self.logger.warning(
                "Size failsafe triggered %d consecutive times (live data %.1f MB > %.1f MB limit)",
                self._consecutive_size_triggers,
                live_mb,
                max_size_mb,
            )

        db = self.db
        total_deleted_by_label: dict[str, int] = {t.failsafe_label: 0 for t in _FAILSAFE_TABLES}
        batch_limit = config.size_failsafe_delete_batch
        max_iterations = config.size_failsafe_max_iterations

        priorities = sorted({t.priority for t in _FAILSAFE_TABLES})
        capped_tier_label: str | None = None
        any_tier_incomplete = False
        iterations_used = 0
        stop_run = False  # a size read failed: end the run, but still shrink and report below
        for priority in priorities:
            group = [t for t in _FAILSAFE_TABLES if t.priority == priority]
            group_label = ", ".join(t.failsafe_label for t in group)
            capped_early = False

            # max_iterations is a shared per-run budget, not a per-tier one -- each tier
            # only gets whatever's left after higher-priority tiers already spent theirs.
            remaining_iterations = max_iterations - iterations_used
            for iteration in range(1, remaining_iterations + 1):
                if iteration % CLEANUP_PROGRESS_LOG_INTERVAL == 0:
                    self.logger.info(
                        "Size failsafe in progress: %s — tier iteration %d, live data %.1f MB (limit %.1f MB)",
                        group_label,
                        iteration,
                        live_mb,
                        max_size_mb,
                    )
                group_deleted = 0
                group_failed = False
                for target in group:
                    try:
                        n = await _execute_failsafe_delete(db, target, batch_limit=batch_limit)
                    except STORAGE_ERRORS:
                        # No rollback here — this connection is opened with isolation_level=None
                        # (autocommit), and unlike the age-based retention path, this loop never
                        # issues an explicit BEGIN, so there is no open transaction to roll back.
                        # Any earlier deletes in this iteration already committed on execute.
                        self.logger.exception(
                            "Size failsafe failed for %s (live data %.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            live_mb,
                            max_size_mb,
                        )
                        group_failed = True
                        continue
                    self._write_progress_count += 1  # the DELETE autocommitted on execute
                    total_deleted_by_label[target.failsafe_label] += n
                    group_deleted += n

                if group_deleted > 0:
                    # Each DELETE autocommits (isolation_level=None, no explicit BEGIN), so rows
                    # removed this iteration are gone for good even if a DELETE on another target
                    # in this group failed. The iteration still counts against the shared budget,
                    # otherwise a lower-priority tier would receive undiminished budget for work
                    # that already happened.
                    iterations_used += 1

                if group_failed:
                    # This priority tier had a DELETE failure — stop retrying it and
                    # move on to the next tier instead of aborting the whole failsafe run. The
                    # next hourly cycle retries this tier from scratch.
                    any_tier_incomplete = True
                    break

                if group_deleted == 0:
                    # An empty tier (already fully drained by an earlier cycle) costs nothing —
                    # only a batch that actually deletes rows spends the shared budget. Without
                    # this, an always-empty higher-priority tier would spend one iteration every
                    # single cycle just confirming it's still empty, permanently starving
                    # lower-priority tiers of budget they'd otherwise get (catastrophically so at
                    # size_failsafe_max_iterations=1, where that confirmation alone eats the
                    # entire run).
                    break

                measured = await self.read_live_data_mb_or_none()
                if measured is None:
                    any_tier_incomplete = True
                    stop_run = True
                    break
                live_mb = measured
                if live_mb <= max_size_mb:
                    break
            else:
                # Every iteration this tier got ran full-sized (or the shared budget was
                # already spent by a higher-priority tier, leaving remaining_iterations at 0),
                # but that doesn't prove this tier's own rows remain — the final full batch may
                # have drained this tier's last row while the database stays oversized only
                # because of other, lower-priority tiers. Probe before declaring this tier
                # capped; an unnecessary cap here would skip those other tiers unnecessarily.
                for target in group:
                    where_clause, stale_params = build_tier_where(target)
                    try:
                        # Closed before shrink_database_file() runs: an open read statement on this
                        # connection makes wal_checkpoint fail with "database table is locked".
                        stale_cursor = await db.execute(
                            f"SELECT 1 FROM {target.table} {where_clause}LIMIT 1", stale_params
                        )
                        try:
                            stale_row = await stale_cursor.fetchone()
                        finally:
                            await stale_cursor.close()
                    except STORAGE_ERRORS:
                        # No rollback here either — the probe is a plain SELECT, and (as above)
                        # this loop never opens a transaction to roll back in the first place.
                        self.logger.exception(
                            "Size failsafe stale-row probe failed for %s (live data %.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            live_mb,
                            max_size_mb,
                        )
                        any_tier_incomplete = True
                        continue
                    if stale_row is not None:
                        capped_early = True
                        self.logger.warning(
                            "Size failsafe %s capped at %d iterations; live data still %.1f MB (limit %.1f MB) — "
                            "stopping this cycle without touching lower-priority tiers",
                            group_label,
                            max_iterations,
                            live_mb,
                            max_size_mb,
                        )
                        break

            if stop_run:
                break

            measured = await self.read_live_data_mb_or_none()
            if measured is None:
                any_tier_incomplete = True
                break
            live_mb = measured
            if live_mb <= max_size_mb:
                break

            if capped_early:
                # This tier is still over its per-cycle iteration cap with live data still
                # over the limit — stop here rather than advancing to a lower-priority (more
                # valuable) tier. Advancing would let app-tier data get deleted while this
                # higher-priority tier still has a large backlog of its own, defeating the
                # priority ordering for exactly the high-volume scenario it exists to handle.
                # The next hourly cycle starts again from the lowest priority number, so this
                # tier is retried first.
                capped_tier_label = group_label
                break

        # Every exit from the tier loop reaches here, including a stop after a failed size read.
        if any(total_deleted_by_label.values()):
            await self.shrink_database_file()

        deleted_summary = {label: count for label, count in total_deleted_by_label.items() if count > 0}
        if deleted_summary:
            parts = ", ".join(f"{count} {label}" for label, count in deleted_summary.items())
            self.logger.info("Size failsafe: deleted %s (live data %.1f MB remaining)", parts, live_mb)

        if live_mb > max_size_mb:
            if capped_tier_label is not None or any_tier_incomplete:
                # Either cause breaks any exhaustion streak in progress — the next
                # genuinely-exhausted cycle must not report a count that spans across this
                # interruption. Both causes can occur in the same cycle (an earlier tier's
                # DELETE failure, followed by a later tier hitting its iteration cap) —
                # report every cause that applied instead of only the one checked first, so a
                # capped tier discovered after an earlier failure doesn't hide that failure from
                # the aggregate warning.
                self._consecutive_exhaustion_triggers = 0
                causes = []
                if any_tier_incomplete:
                    causes.append("one or more tiers failed and were skipped this cycle")
                if capped_tier_label is not None:
                    causes.append(
                        f"{capped_tier_label} hit the {max_iterations}-iteration cap "
                        "(lower-priority tiers were not touched this cycle)"
                    )
                self.logger.warning(
                    "Size failsafe stopped early: %s; live data still %.1f MB (limit %.1f MB) — retrying next cycle",
                    "; ".join(causes),
                    live_mb,
                    max_size_mb,
                )
            else:
                self._consecutive_exhaustion_triggers += 1
                self.logger.warning(
                    "Size failsafe exhausted all retention tiers %d consecutive time(s); "
                    "live data still %.1f MB (limit %.1f MB)",
                    self._consecutive_exhaustion_triggers,
                    live_mb,
                    max_size_mb,
                )
        else:
            self._consecutive_exhaustion_triggers = 0

    async def run_size_failsafe(self) -> bool:
        """Enqueue a size failsafe check; False if dropped (no database, or write queue full)."""
        return self.enqueue_if_ready(self._check_size_failsafe)
