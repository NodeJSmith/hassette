"""Size-limit failsafe for ``DatabaseService``, as a mixin."""

import sqlite3
import typing
from pathlib import Path
from typing import Any

import aiosqlite

from hassette.core.retention_targets import _FAILSAFE_TABLES, RetentionTarget, build_tier_where

if typing.TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Callable, Coroutine

    from hassette import Hassette
    from hassette.core.database_write_queue import _WriteQueueItem

_VACUUM_CHECKPOINT_RETRY_ATTEMPTS = 2
"""Attempts _vacuum_and_checkpoint_with_retry() makes for the incremental_vacuum/wal_checkpoint
pair before giving up on the current tier. One retry absorbs a transient lock; a second
consecutive failure moves on to the next priority tier instead of retrying indefinitely."""


async def _execute_failsafe_delete(
    db: aiosqlite.Connection,
    target: RetentionTarget,
    *,
    batch_limit: int,
) -> int:
    """Delete the oldest ``batch_limit`` rows in ``target.table``, filtered by
    ``target.source_tier`` when set, for the size failsafe.

    Does not manage transactions -- the caller owns commit.
    """
    where_clause, params = build_tier_where(target)
    cursor = await db.execute(
        f"DELETE FROM {target.table} WHERE id IN "
        f"(SELECT id FROM {target.table} {where_clause}ORDER BY {target.timestamp_col} ASC LIMIT ?)",
        [*params, batch_limit],
    )
    return cursor.rowcount or 0


class DatabaseSizeFailsafeMixin:
    """Size-failsafe methods of ``DatabaseService``; reads the host attributes declared below."""

    hassette: "Hassette"
    logger: "logging.Logger"
    _db: aiosqlite.Connection | None
    _db_path: Path
    _db_write_queue: "asyncio.Queue[_WriteQueueItem] | None"
    _consecutive_size_triggers: int
    _consecutive_exhaustion_triggers: int
    db: aiosqlite.Connection
    enqueue: "Callable[[Coroutine[Any, Any, Any]], bool]"

    def get_db_size_mb(self) -> float:
        """Return total database size (main + WAL + SHM) in megabytes."""
        total = 0
        for suffix in ("", "-wal", "-shm"):
            path = Path(str(self._db_path) + suffix)
            if path.exists():
                total += path.stat().st_size
        return total / (1024 * 1024)

    async def _vacuum_and_checkpoint_with_retry(
        self, db: aiosqlite.Connection, vacuum_pages: int, group_label: str
    ) -> bool:
        """Run PRAGMA incremental_vacuum + wal_checkpoint(TRUNCATE), retrying on failure.

        Returns True if the vacuum/checkpoint pair succeeded on any attempt (up to
        ``_VACUUM_CHECKPOINT_RETRY_ATTEMPTS``), False if every attempt failed.
        """
        for attempt in range(_VACUUM_CHECKPOINT_RETRY_ATTEMPTS):
            try:
                vacuum_cursor = await db.execute(f"PRAGMA incremental_vacuum({vacuum_pages})")
                await vacuum_cursor.close()
                checkpoint_cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                checkpoint_row = await checkpoint_cursor.fetchone()
                await checkpoint_cursor.close()
                # wal_checkpoint(TRUNCATE) doesn't raise when it's blocked (SQLITE_BUSY) -- it
                # returns a row whose first column is nonzero instead. Treat a missing row or a
                # nonzero busy value as a failed attempt so it's caught below and retried like
                # any other vacuum/checkpoint failure.
                if checkpoint_row is None or checkpoint_row[0] != 0:
                    raise sqlite3.OperationalError(f"wal_checkpoint(TRUNCATE) busy or failed: {checkpoint_row}")
                return True
            except Exception:
                attempts_left = _VACUUM_CHECKPOINT_RETRY_ATTEMPTS - attempt - 1
                if attempts_left > 0:
                    self.logger.warning(
                        "Size failsafe: vacuum/checkpoint failed for %s, %d attempt(s) left",
                        group_label,
                        attempts_left,
                    )
                else:
                    self.logger.exception(
                        "Size failsafe: vacuum/checkpoint failed after %d attempts for %s, moving to next tier",
                        _VACUUM_CHECKPOINT_RETRY_ATTEMPTS,
                        group_label,
                    )
        return False

    async def _check_size_failsafe(self) -> None:
        """Delete oldest records if database exceeds the configured size limit.

        Iterates _FAILSAFE_TABLES grouped by priority (lower priority number = deleted
        first) — targets marked ``failsafe_exempt`` are never touched here, no matter how far
        over the limit the database is. Within each priority tier, all tables in the group are
        deleted together per iteration; a target's ``source_tier`` filter (when set) is applied
        inside the inner SELECT so each tier's own oldest-N rows are deleted, not the
        globally-oldest N rows filtered down afterward. After each iteration a vacuum+checkpoint
        (with a single bounded retry — see ``_vacuum_and_checkpoint_with_retry()``) reclaims
        disk space. The process stops as soon as the database falls within the size limit.

        ``max_iterations`` is a single budget shared across the whole run, not a per-tier
        allowance — each tier only gets whatever iterations remain after higher-priority
        tiers have spent theirs, so a run never deletes more than ``max_iterations`` batches
        total regardless of how many priority tiers it touches. The budget is spent only by
        a batch that actually deletes rows — a tier that's already fully drained still needs
        one attempt to confirm it has nothing left, but that attempt is free, so an
        always-empty higher-priority tier can't permanently starve lower-priority tiers of
        budget on every future cycle just by existing.

        If a tier's iteration loop runs out of its share of the budget without naturally draining
        (every iteration deletes a full batch), the tier is only treated as capped after
        probing whether it still has matching rows — the same stale-row check
        ``_delete_target_batched()`` uses. An exact-boundary final batch can drain the tier's
        own rows while the database stays oversized purely because of other, lower-priority
        tiers; probing avoids stopping there and skipping those tiers unnecessarily. When the
        probe confirms rows remain, the run stops instead of advancing to the next,
        lower-priority tier — a capped tier still has a large backlog of higher-value data of
        its own, and deleting app-tier data while that backlog remains would defeat the priority
        ordering. The next hourly cycle retries the capped tier first.

        A DELETE failure on one priority tier is logged with the target's ``failsafe_label``,
        current size, and limit, then skipped — subsequent, lower-priority tiers still run
        rather than the whole failsafe run silently aborting. The failed tier retries on the
        next hourly cycle. The stale-row probe above is isolated the same way: a probe failure
        is logged and skips the rest of that tier rather than propagating out of this method.
        A vacuum/checkpoint failure that exhausts its retry is treated the same way — the tier
        is marked incomplete and the run moves on to the next tier.

        ``_consecutive_exhaustion_triggers`` is only incremented when every tier genuinely
        drained (no capped tier, no DELETE/vacuum failure) and the database is still over the
        limit — a cycle that stopped early on a capped tier or skipped a tier after a failure
        does not count as "exhausted," since the overage there is attributable to the
        stop/skip rather than to unmanaged data across every tier. Such a cycle also resets the
        counter to 0, so a later genuinely-exhausted cycle reports a fresh streak rather than
        one that silently spans the interruption. A WARNING is logged for every over-limit
        cycle, naming every cause that applied — a capped tier, one or more skipped/failed
        tiers, or (when neither applied) that every tier drained without resolving the
        overage — rather than only the first cause checked.
        """
        config = self.hassette.config.database
        max_size_mb = config.max_size_mb
        if max_size_mb == 0:
            return

        current_size = self.get_db_size_mb()
        if current_size <= max_size_mb:
            self._consecutive_size_triggers = 0
            self._consecutive_exhaustion_triggers = 0
            return

        self._consecutive_size_triggers += 1
        if self._consecutive_size_triggers > 1:
            self.logger.warning(
                "Size failsafe triggered %d consecutive times (%.1f MB > %.1f MB limit)",
                self._consecutive_size_triggers,
                current_size,
                max_size_mb,
            )

        db = self.db
        total_deleted_by_label: dict[str, int] = {t.failsafe_label: 0 for t in _FAILSAFE_TABLES}
        batch_limit = config.size_failsafe_delete_batch
        max_iterations = config.size_failsafe_max_iterations
        vacuum_pages = config.size_failsafe_vacuum_pages

        priorities = sorted({t.priority for t in _FAILSAFE_TABLES})
        capped_tier_label: str | None = None
        any_tier_incomplete = False
        iterations_used = 0
        for priority in priorities:
            group = [t for t in _FAILSAFE_TABLES if t.priority == priority]
            group_label = ", ".join(t.failsafe_label for t in group)
            capped_early = False

            # max_iterations is a shared per-run budget, not a per-tier one -- each tier
            # only gets whatever's left after higher-priority tiers already spent theirs.
            remaining_iterations = max_iterations - iterations_used
            for _iteration in range(remaining_iterations):
                group_deleted = 0
                group_failed = False
                for target in group:
                    try:
                        n = await _execute_failsafe_delete(db, target, batch_limit=batch_limit)
                    except Exception:
                        # No rollback here — this connection is opened with isolation_level=None
                        # (autocommit), and unlike the age-based retention path, this loop never
                        # issues an explicit BEGIN, so there is no open transaction to roll back.
                        # Any earlier deletes in this iteration already committed on execute.
                        self.logger.exception(
                            "Size failsafe failed for %s (%.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            current_size,
                            max_size_mb,
                        )
                        group_failed = True
                        continue
                    total_deleted_by_label[target.failsafe_label] += n
                    group_deleted += n

                # Commit whatever succeeded this iteration before vacuuming. PRAGMA
                # wal_checkpoint(TRUNCATE) below cannot run while the delete statements hold a
                # write lock — without this commit it fails with "database table is locked".
                try:
                    await db.commit()
                except Exception:
                    # Isolated the same way as a DELETE failure above — an uncaught commit
                    # failure would otherwise escape this method entirely, skipping every
                    # lower-priority tier and the aggregate any_tier_incomplete/exhaustion
                    # accounting below rather than just this one tier.
                    self.logger.exception(
                        "Size failsafe commit failed for %s (%.1f MB > %.1f MB limit)",
                        group_label,
                        current_size,
                        max_size_mb,
                    )
                    group_failed = True

                if group_deleted > 0:
                    # The DELETE(s) above already autocommitted — isolation_level=None and no
                    # explicit BEGIN means each execute() durably persisted immediately. Any
                    # rows removed this iteration are gone from the database for good
                    # regardless of whether the commit() call above (or a DELETE on another
                    # target in this group) subsequently failed, so this iteration must still
                    # count against the shared budget — otherwise a commit failure would let a
                    # lower-priority tier receive undiminished budget for real work that
                    # already happened (e.g. two full batches deleted in the same run at
                    # size_failsafe_max_iterations=1, one from this tier and one from the next).
                    iterations_used += 1

                if group_failed:
                    # This priority tier had a DELETE or commit failure — stop retrying it and
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

                # A single bounded retry: a transient vacuum/checkpoint failure (e.g. a
                # momentary lock) shouldn't push the failsafe into deleting from a more
                # valuable tier based on a size reading that's stale only because the WAL
                # wasn't truncated -- the deletes already happened.
                vacuum_ok = await self._vacuum_and_checkpoint_with_retry(db, vacuum_pages, group_label)
                if not vacuum_ok:
                    any_tier_incomplete = True
                    break

                current_size = self.get_db_size_mb()
                if current_size <= max_size_mb:
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
                        stale_cursor = await db.execute(
                            f"SELECT 1 FROM {target.table} {where_clause}LIMIT 1", stale_params
                        )
                        stale_row = await stale_cursor.fetchone()
                    except Exception:
                        # No rollback here either — the probe is a plain SELECT, and (as above)
                        # this loop never opens a transaction to roll back in the first place.
                        self.logger.exception(
                            "Size failsafe stale-row probe failed for %s (%.1f MB > %.1f MB limit)",
                            target.failsafe_label,
                            current_size,
                            max_size_mb,
                        )
                        any_tier_incomplete = True
                        continue
                    if stale_row is not None:
                        capped_early = True
                        self.logger.warning(
                            "Size failsafe %s capped at %d iterations; database still %.1f MB (limit %.1f MB) — "
                            "stopping this cycle without touching lower-priority tiers",
                            group_label,
                            max_iterations,
                            current_size,
                            max_size_mb,
                        )
                        break

            current_size = self.get_db_size_mb()
            if current_size <= max_size_mb:
                break

            if capped_early:
                # This tier is still over its per-cycle iteration cap with the database still
                # over the limit — stop here rather than advancing to a lower-priority (more
                # valuable) tier. Advancing would let app-tier data get deleted while this
                # higher-priority tier still has a large backlog of its own, defeating the
                # priority ordering for exactly the high-volume scenario it exists to handle.
                # The next hourly cycle starts again from the lowest priority number, so this
                # tier is retried first.
                capped_tier_label = group_label
                break

        deleted_summary = {label: count for label, count in total_deleted_by_label.items() if count > 0}
        if deleted_summary:
            parts = ", ".join(f"{count} {label}" for label, count in deleted_summary.items())
            self.logger.info("Size failsafe: deleted %s (%.1f MB remaining)", parts, current_size)

        if current_size > max_size_mb:
            if capped_tier_label is not None or any_tier_incomplete:
                # Either cause breaks any exhaustion streak in progress — the next
                # genuinely-exhausted cycle must not report a count that spans across this
                # interruption. Both causes can occur in the same cycle (an earlier tier's
                # DELETE/vacuum failure, followed by a later tier hitting its iteration cap) —
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
                    "Size failsafe stopped early: %s; database still %.1f MB (limit %.1f MB) — retrying next cycle",
                    "; ".join(causes),
                    current_size,
                    max_size_mb,
                )
            else:
                self._consecutive_exhaustion_triggers += 1
                self.logger.warning(
                    "Size failsafe exhausted all retention tiers %d consecutive time(s); "
                    "database still %.1f MB (limit %.1f MB)",
                    self._consecutive_exhaustion_triggers,
                    current_size,
                    max_size_mb,
                )
        else:
            self._consecutive_exhaustion_triggers = 0

    async def run_size_failsafe(self) -> bool:
        """Enqueue a size failsafe check; False if dropped (no database, or write queue full)."""
        if self._db is None or self._db_write_queue is None:
            return False
        return self.enqueue(self._check_size_failsafe())
