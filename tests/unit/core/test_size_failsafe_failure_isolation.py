"""Unit tests for size-failsafe failure isolation and exhaustion-streak resets."""

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
    make_failing_execute,
    make_log_record_row,
    mock_hassette_for_db,
    retention_service,
    run_size_failsafe,
)

__all__ = ["db", "db_service_writer", "mock_hassette_for_db", "retention_service"]  # re-exposed as fixtures


class TestSizeFailsafeFailureIsolation:
    """A failing tier is isolated and skipped; later tiers and the exhaustion streak behave correctly."""

    async def test_size_failsafe_stale_row_probe_failure_isolated(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient error from the size-failsafe's own stale-row probe (the twin of
        ``_delete_target_batched()``'s probe, reached only when a tier's iteration loop runs to
        completion without naturally draining) is caught and isolated to that tier — not an
        uncaught exception that aborts the whole failsafe cycle and skips lower-priority tiers.

        Regression test: this probe was added alongside the retention-path probe's isolation
        fix (see ``test_stale_row_probe_failure_isolated_to_target``) but was itself initially
        left unguarded, reproducing the exact bug class this PR exists to fix.
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Framework tier: far more rows than the 2-iteration * 2-row cap (4) can ever drain —
        # every iteration deletes a full batch, so the loop runs to completion and reaches the
        # probe instead of breaking early via group_deleted == 0.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        # A lower-priority tier the run can still reach after the framework tier's probe fails.
        await insert_blocking_event(db, now - 1)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        # Fail only the stale-row probe's SELECT, not the batched DELETE's inner subselect.
        monkeypatch.setattr(db, "execute", make_failing_execute(db, "SELECT 1 FROM executions"))

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # The framework tier's probe failed and was skipped rather than the whole run aborting —
        # the lower-priority blocking-events tier was still evaluated this cycle. It's left
        # untouched (framework's own drain-then-confirm spent the entire shared budget) and
        # correctly reported as capped rather than silently skipped.
        assert await count_rows(db, "blocking_events") == 1
        assert "Size failsafe blocking events capped at 2 iterations" in caplog.text
        # The exempt table is never in the chain at all, capped or not.
        assert await count_rows(db, "log_records") == 1

        assert "Size failsafe stale-row probe failed for framework executions" in caplog.text
        # A probe failure is not a genuine full-tier drain — must not count as exhaustion.
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_capped_cycle_resets_exhaustion_streak(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A capped-but-not-exhausted cycle must reset ``_consecutive_exhaustion_triggers`` to 0,
        not merely leave it unchanged — otherwise a later genuinely-exhausted cycle reports a
        streak count that silently spans the interruption.

        Regression test: run 1 fully exhausts every tier (counter -> 1). Run 2's framework tier
        hits its iteration cap and stops the cycle early (not a genuine drain) — the counter must
        drop to 0, not stay at 1. Run 3 fully exhausts again — the counter must read 1 (a fresh
        streak), not 2 (as if run 2's interruption never happened).
        """
        retention_service.hassette.config.database.size_failsafe_max_iterations = 2
        retention_service.hassette.config.database.size_failsafe_delete_batch = 2

        now = time.time()
        # Every run below goes through run_size_failsafe's always-over-limit size mock, so every
        # over-limit branch (exhaustion, capped) is exercised deliberately by row counts rather
        # than by the mocked size flipping under the limit.

        # Run 1: a single framework row and a single log record — small enough that both tiers
        # naturally drain within the 2-iteration cap. Every tier drains, DB still over limit ->
        # genuine exhaustion.
        await insert_tiered_execution(db, now - 1, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 1, "log")]
        )

        await run_size_failsafe(retention_service, mock_hassette_for_db)
        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]

        # Run 2: a framework backlog far larger than the 2-iteration * 2-row cap (4) can ever
        # drain — the tier hits its iteration cap, the stale-row probe finds rows remain, and the
        # cycle stops early instead of advancing. This is the capped path, not a genuine drain.
        for i in range(20):
            await insert_tiered_execution(db, now - i, SOURCE_TIER_FRAMEWORK)
        await db.commit()

        await run_size_failsafe(retention_service, mock_hassette_for_db)
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

        # Run 3: clear the leftover framework backlog (simulating it having been resolved by an
        # intervening cycle) and seed a small amount of fresh data that again drains every tier
        # naturally within the cap — a genuine exhaustion, starting a fresh streak.
        await db.execute("DELETE FROM executions WHERE source_tier = 'framework'")
        await db.commit()
        await insert_tiered_execution(db, now - 1, SOURCE_TIER_FRAMEWORK)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(2, now - 1, "log")]
        )

        await run_size_failsafe(retention_service, mock_hassette_for_db)
        assert retention_service._consecutive_exhaustion_triggers == 1  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_failure_isolation(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        caplog: pytest.LogCaptureFixture,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A DELETE failure on one priority tier is logged with its label, current size, and
        limit, and does not abort lower-priority tiers — the size-failsafe analog of
        ``TestRetentionCleanup.test_per_target_failure_isolation``.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()

        original_execute = db.execute

        async def failing_framework_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            if (
                sql.strip().startswith("DELETE FROM executions")
                and args
                and args[0]
                and SOURCE_TIER_FRAMEWORK in args[0]
            ):
                raise sqlite3.OperationalError("simulated failure")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", failing_framework_execute)

        await run_size_failsafe(retention_service, mock_hassette_for_db, caplog)

        # Framework executions tier failed and is left untouched.
        assert await count_rows(db, "executions", source_tier="framework") == 1

        # Lower-priority tiers still ran despite the framework-tier failure.
        assert await count_rows(db, "blocking_events") == 0
        assert await count_rows(db, "executions", source_tier="app") == 0

        assert "Size failsafe failed for framework executions" in caplog.text
        assert "10.0 MB" in caplog.text  # current size
        assert "0.0 MB limit" in caplog.text  # SIZE_FAILSAFE_TRIGGER_MB formatted to 1 decimal

        # A tier failing and being skipped is not a genuine full-drain exhaustion — counting it
        # would misattribute the overage to unmanaged data rather than the failed cleanup that
        # actually caused it.
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]
        assert "failed and were skipped this cycle" in caplog.text
