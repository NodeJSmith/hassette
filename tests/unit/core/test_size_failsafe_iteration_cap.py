"""Unit tests for size-failsafe iteration caps, the shared iteration budget, and exhaustion warnings."""

import logging
import sqlite3
import time
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService

from ._fixtures_retention import (
    SOURCE_TIER_APP,
    SOURCE_TIER_FRAMEWORK,
    count_rows,
    db,
    db_service_writer,
    insert_blocking_event,
    insert_tiered_execution,
    make_log_record_row,
    mock_hassette_for_db,
    retention_service,
    run_size_failsafe,
)

__all__ = ["db", "db_service_writer", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures


class TestSizeFailsafeIterationCap:
    """Iteration caps, the shared iteration budget, and exhaustion warnings across failsafe tiers."""

    async def test_size_failsafe_logs_exhaustion_warning_with_consecutive_count(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
    ) -> None:
        """A run that drains every tier and remains over the size limit logs a WARNING naming
        the consecutive exhaustion count.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 10, "log")]
        )

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog, level=logging.WARNING)

        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]
        assert "exhausted" in caplog.text
        assert "1 consecutive" in caplog.text

        caplog.clear()
        # Re-seed (previous run deleted everything) and run again — count must increment.
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog, level=logging.WARNING)

        assert retention_service._consecutive_exhaustion_triggers == 2  # pyright: ignore[reportPrivateUsage]
        assert "2 consecutive" in caplog.text

    async def test_size_failsafe_stops_when_higher_priority_tier_hits_iteration_cap(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the highest-priority tier (framework executions) hits its per-cycle iteration
        cap while the database is still over the limit, the run must stop there rather than
        advancing to lower-priority tiers — deleting app/log data while the higher-priority
        tier's own backlog remains would defeat the priority ordering the tiers exist for.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: far more rows than the 2-iteration * 2-row cap (4) can ever drain.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        # Always over the limit, so the framework tier hits the iteration cap instead of naturally
        # draining and breaking out early.
        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # Only the capped iterations' worth was deleted (2 iterations * 2 rows = 4); the tier's
        # own large remaining backlog proves the run stopped rather than exhausting the tier.
        assert await count_rows(db, "executions", source_tier="framework") == 16

        # Lower-priority tier (log_records) was never touched.
        assert await count_rows(db, "log_records") == 1

        assert "capped at 2 iterations" in caplog.text
        assert "stopped early" in caplog.text
        assert "framework executions" in caplog.text

    async def test_size_failsafe_reports_both_causes_when_earlier_tier_fails_and_later_tier_caps(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a higher-priority tier's DELETE fails (``any_tier_incomplete``) and a
        lower-priority tier later hits its iteration cap (``capped_tier_label``) in the same
        cycle, the end-of-cycle warning must name both causes — not just whichever one the
        code happens to check first.

        Regression test for the original if/capped-elif-incomplete structure, which could only
        ever report one cause and silently dropped the other from the aggregate warning.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier (priority 1, highest): its DELETE always fails below.
        await insert_tiered_execution(db, now - 1, SOURCE_TIER_FRAMEWORK)
        # App executions tier (priority 3): far more rows than the 2-iteration * 2-row cap (4)
        # can ever drain, so it hits the iteration cap. Framework's failed attempt and blocking
        # events' empty-tier check both cost nothing against the shared budget, so app still
        # gets the full 2 iterations.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_APP)
        await db.commit()

        original_execute = db.execute

        async def failing_framework_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            if (
                sql.strip().startswith("DELETE FROM executions")
                and args
                and args[0]
                and args[0][0] == SOURCE_TIER_FRAMEWORK
            ):
                raise sqlite3.OperationalError("simulated failure")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_framework_execute)

        # Always over the limit, so the framework tier hits the iteration cap instead of naturally
        # draining and breaking out early.
        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # Framework tier's DELETE always failed — untouched.
        assert await count_rows(db, "executions", source_tier="framework") == 1

        # App tier hit its cap (2 iterations * 2 rows = 4 deleted, 16 remain).
        assert await count_rows(db, "executions", source_tier="app") == 16

        assert "Size failsafe stopped early" in caplog.text
        assert "one or more tiers failed and were skipped this cycle" in caplog.text
        assert "app executions hit the 2-iteration cap" in caplog.text
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_iteration_budget_is_shared_across_tiers(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
    ) -> None:
        """``size_failsafe_max_iterations`` bounds the whole run, not each priority tier
        individually — a tier only gets whatever iterations remain after higher-priority tiers
        have already spent theirs, and a tier that runs out of shared budget mid-drain is
        capped (stopping the cycle) rather than the run silently granting every tier its own
        fresh allotment.

        Regression test: the size failsafe previously called ``range(max_iterations)`` fresh
        for every priority tier, so a 4-tier run could execute up to 4x the configured number
        of delete batches and drain every tier in one cycle instead of stopping once the
        configured total was spent.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier (priority 1) and blocking events (priority 2): exactly 2 rows each —
        # 1 productive iteration apiece, fully consuming the 2-iteration shared budget between
        # them with nothing "wasted" on an empty-tier check.
        for i in range(2):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        for i in range(2):
            await insert_blocking_event(db, now - i)
        # App executions (priority 3): seeded so an untouched count is provable, but must never
        # be reached once the budget is spent on the two higher-priority tiers above. The log
        # records below are seeded for the same reason, but survive by exemption, not by budget.
        for i in range(5):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_APP)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(i, now - i, "log") for i in range(5)]
        )

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # Framework tier used 1 of the 2-iteration budget and fully drained.
        assert await count_rows(db, "executions", source_tier="framework") == 0

        # Blocking events got the 1 remaining iteration and also fully drained -- not a fresh
        # budget of its own, just what framework left behind.
        assert await count_rows(db, "blocking_events") == 0

        # App executions were never reached — the shared budget ran out before the run could
        # advance past blocking events. Log records survive for the unrelated reason that they
        # are exempt, so they would be intact here even with an unlimited budget.
        assert await count_rows(db, "executions", source_tier="app") == 5
        assert await count_rows(db, "log_records") == 5

        assert "app executions capped at 2 iterations" in caplog.text
        assert "stopped early" in caplog.text
        assert "app executions hit the 2-iteration cap" in caplog.text
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_empty_tier_does_not_consume_shared_budget(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
    ) -> None:
        """Confirming an already-drained tier has nothing left must not spend any of the
        shared iteration budget — only a batch that actually deletes rows does. Otherwise an
        always-empty higher-priority tier spends one iteration every single cycle just
        re-confirming it's still empty, permanently starving lower-priority tiers of budget
        they would otherwise get — catastrophically so at
        ``size_failsafe_max_iterations=1``, where that single wasted confirmation would
        consume the entire run's budget forever, on every future cycle, even once the
        higher-priority tier has been empty for a long time.

        Regression test: ``iterations_used`` was originally incremented unconditionally at
        the top of every attempt, before knowing whether the DELETE removed anything.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 1
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier (priority 1): no rows -- the steady state a deployment settles into
        # once its backlog is cleared. Blocking events (priority 2): exactly one batch's
        # worth -- provable only if the single-iteration budget actually reaches it instead of
        # being spent "confirming" the already-empty framework tier.
        await insert_blocking_event(db, now - 1)
        await insert_blocking_event(db, now - 2)
        await db.commit()

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # The single iteration was spent draining blocking events, not wasted confirming the
        # already-empty framework tier is still empty.
        assert await count_rows(db, "blocking_events") == 0
        assert "capped" not in caplog.text

    async def test_size_failsafe_exact_boundary_drain_proceeds_to_next_tier(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When a tier's row count is an exact multiple of the iteration cap * batch size, the
        final full batch drains the tier's own rows even though every iteration ran full-sized.
        The tier itself must not be treated as capped just because the database is still over
        the limit — the stale-row probe must correctly find no remaining rows for that tier.

        Because ``size_failsafe_max_iterations`` is a budget shared across the whole run (see
        ``test_size_failsafe_iteration_budget_is_shared_across_tiers``), an exact-boundary drain
        that consumes a tier's entire allotment leaves nothing for the next tier this cycle — a
        lower-priority tier that still has rows of its own is correctly capped rather than
        silently granted a fresh budget of its own.

        Regression test: the size failsafe previously declared a tier capped whenever its
        iteration loop ran to the cap while the database stayed oversized, without checking
        whether the tier's own rows were actually exhausted.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: exactly 2 iterations * 2 rows = 4 rows — the final full batch drains
        # the tier's own last row, consuming the run's entire 2-iteration shared budget.
        for i in range(4):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        # Blocking events (priority 2): the sole reason the DB stays over limit after the
        # framework tier drains — correctly capped, since no budget remains this cycle.
        await insert_blocking_event(db, now - 1)
        await db.commit()

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # Framework tier fully drained by the exact-boundary final batch — and the stale-row
        # probe correctly found no remaining framework rows, so it was never itself capped.
        assert await count_rows(db, "executions", source_tier="framework") == 0
        assert "framework executions capped" not in caplog.text

        # Blocking events was left untouched — the shared budget was fully spent draining the
        # higher-priority framework tier, so it's correctly capped rather than drained via an
        # illegitimate fresh budget of its own.
        assert await count_rows(db, "blocking_events") == 1

        assert "blocking events capped at 2 iterations" in caplog.text
        assert "stopped early" in caplog.text
