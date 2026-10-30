"""Unit tests for size-failsafe tier priority ordering and per-tier delete scoping."""

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


class TestSizeFailsafePriority:
    """Priority ordering per ``_FAILSAFE_TABLES``: framework executions (1) < blocking events (2)
    < app executions (3). ``log_records`` is ``failsafe_exempt`` and never appears in this chain
    at all — it expires only through age-based retention.
    The DELETE queries filter by ``source_tier`` inside the inner SELECT (when a target declares
    one), so each tier's own oldest-N rows are targeted rather than the globally-oldest N rows
    filtered down afterward.
    """

    async def seed_both_tables(
        self, db: aiosqlite.Connection, db_service_writer: DatabaseService, log_count: int = 10, exec_count: int = 5
    ) -> None:
        """Seed log_records and executions."""
        now = time.time()
        logs = [make_log_record_row(i, now - (i * 10), f"log {i}") for i in range(1, log_count + 1)]
        await db_service_writer._insert_log_records(logs)  # pyright: ignore[reportPrivateUsage]

        for i in range(exec_count):
            await db.execute(
                "INSERT INTO executions (kind, listener_id, execution_start_ts) VALUES ('handler', 1, ?)",
                (now - i * 10,),
            )
        await db.commit()

    async def test_size_failsafe_stops_deleting_executions_once_under_limit(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """The failsafe stops mid-drain as soon as the database is back under the limit.

        ``seed_both_tables`` inserts executions without an explicit ``source_tier``, so they
        fall in the default 'app' tier (priority 3) — the framework tier (priority 1) and
        blocking_events (priority 2) are empty and each consume one end-of-priority size check
        before priority 3 is even reached: entry check, priority-1-empty, and priority-2-empty
        (3 checks) precede the priority-3 batch that actually deletes rows.
        """
        await self.seed_both_tables(db, db_service_writer, log_count=10, exec_count=5)

        # Call sites of get_live_data_size_mb(): 1 = entry check, then one per delete batch that
        # removed rows, and one at the end of each priority tier.
        calls = 0

        async def mock_size() -> float:
            nonlocal calls
            calls += 1
            if calls <= 3:
                return 10.0
            return 0.0

        await run_size_failsafe(retention_service, mock_hassette_for_db, live_size=mock_size)

        assert await count_rows(db, "executions") < 5  # partially drained, then stopped
        assert await count_rows(db, "log_records") == 10  # exempt, so intact here and in every scenario

    async def test_size_failsafe_stops_without_raising_when_live_size_read_fails(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """A failing size read after the entry check ends the run cleanly and counts as incomplete."""
        await self.seed_both_tables(db, db_service_writer, log_count=2, exec_count=5)
        calls = 0

        async def failing_after_entry_check() -> float:
            nonlocal calls
            calls += 1
            if calls > 1:
                raise sqlite3.OperationalError("simulated PRAGMA failure")
            return 10.0

        await run_size_failsafe(retention_service, mock_hassette_for_db, live_size=failing_after_entry_check)

        assert await count_rows(db, "executions") == 5  # the framework tier ended the run before app executions
        assert retention_service._consecutive_exhaustion_triggers == 0  # pyright: ignore[reportPrivateUsage]

    async def test_size_failsafe_keeps_log_records_when_execution_deletion_insufficient(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """Draining every failsafe tier without getting under the limit still leaves
        ``log_records`` fully intact — the exemption is absolute, not a last resort.
        """
        await self.seed_both_tables(db, db_service_writer, log_count=5, exec_count=2)

        # Never under the limit — every failsafe tier drains and the run still can't recover.
        await run_size_failsafe(retention_service, mock_hassette_for_db)

        assert await count_rows(db, "executions") == 0
        assert await count_rows(db, "log_records") == 5

    async def test_size_failsafe_scopes_delete_to_own_tier_not_globally_oldest(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        retention_service: DatabaseService,
    ) -> None:
        """The tier filter must live inside the inner SELECT, not the outer DELETE.

        Seeds 5 framework-tier executions and 1 app-tier execution whose timestamp is far
        older than any framework row — the app row is the globally-oldest row overall. With
        the batch size forced below the framework tier's row count, a single batch must
        delete exactly the oldest N *framework* rows and leave the app row untouched. If the
        tier filter were applied on the outer DELETE instead of the inner SELECT, the inner
        SELECT would rank the app row among the batch's oldest IDs, the outer filter would
        discard it, and fewer than N framework rows would be deleted in the batch.
        """
        retention_service.hassette.config.database.size_failsafe_delete_batch = 3

        now = time.time()
        # Framework tier: ages 10, 20, 30, 40, 50 seconds ago (50 is the tier's oldest).
        framework_ages = [10, 20, 30, 40, 50]
        for age in framework_ages:
            await insert_tiered_execution(db, now - age, SOURCE_TIER_FRAMEWORK)
        # App tier: a single row far older than every framework row — globally oldest overall.
        await insert_tiered_execution(db, now - 100_000, SOURCE_TIER_APP)
        # Untouched control rows in the lower-priority groups.
        await insert_blocking_event(db, now - 1)
        await db.commit()

        # Call sites of get_live_data_size_mb(): 1 = entry check, then one per delete batch that
        # removed rows, and one at the end of each priority tier.
        calls = 0

        async def mock_size() -> float:
            nonlocal calls
            calls += 1
            # Over limit for the entry check; under limit immediately after the first
            # batch — confines the whole run to a single priority-1 batch.
            return 10.0 if calls <= 1 else 0.0

        await run_size_failsafe(retention_service, mock_hassette_for_db, live_size=mock_size)

        cursor = await db.execute(
            "SELECT execution_start_ts FROM executions WHERE source_tier = 'framework' ORDER BY execution_start_ts"
        )
        remaining_framework = [row[0] for row in await cursor.fetchall()]
        # The batch (LIMIT 3) deletes the 3 oldest framework rows (ages 50, 40, 30); the 2
        # newest (ages 20, 10) survive.
        assert len(remaining_framework) == 2
        assert sorted(now - ts for ts in remaining_framework) == sorted([10, 20])

        # The app-tier row (globally oldest) must survive — it is not part of the framework tier.
        assert await count_rows(db, "executions", source_tier="app") == 1

        # Lower-priority groups (blocking_events, log_records) are never reached.
        assert await count_rows(db, "blocking_events") == 1

    async def test_size_failsafe_full_priority_chain_order(
        self,
        db: aiosqlite.Connection,
        db_service_writer: DatabaseService,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When the DB stays over limit through every tier, deletion proceeds framework
        executions -> blocking events -> app executions, in that order, and stops there —
        the exempt ``log_records`` is never reached however far over the limit the DB stays.
        """
        now = time.time()
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_FRAMEWORK)
        await insert_blocking_event(db, now - 10)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()
        await db_service_writer._insert_log_records(  # pyright: ignore[reportPrivateUsage]
            [make_log_record_row(1, now - 10, "log")]
        )

        original_execute = db.execute
        delete_order: list[str] = []

        async def tracking_execute(sql: str, *args: Any, **kwargs: Any) -> Any:
            stripped = sql.strip()
            if stripped.startswith("DELETE FROM executions") and args and args[0] and SOURCE_TIER_FRAMEWORK in args[0]:
                delete_order.append("framework executions")
            elif stripped.startswith("DELETE FROM executions") and args and args[0] and SOURCE_TIER_APP in args[0]:
                delete_order.append("app executions")
            elif stripped.startswith("DELETE FROM blocking_events"):
                delete_order.append("blocking events")
            elif stripped.startswith("DELETE FROM log_records"):
                # Tripwire, not a live branch: log_records is failsafe_exempt, so reaching this
                # means the exemption regressed and the unique_order assertion below will fail.
                delete_order.append("log records")
            return await original_execute(sql, *args, **kwargs)

        monkeypatch.setattr(db, "execute", tracking_execute)

        # Always report over limit so the failsafe drains every group.
        await run_size_failsafe(retention_service, mock_hassette_for_db)

        # Each group's inner loop runs one extra (no-op) iteration after draining its rows, so
        # dedupe consecutive repeats while preserving first-seen order.
        unique_order = list(dict.fromkeys(delete_order))
        assert unique_order == ["framework executions", "blocking events", "app executions"]

        assert await count_rows(db, "log_records") == 1

    async def test_size_failsafe_blocking_events_deleted_at_priority_two(
        self,
        db: aiosqlite.Connection,
        mock_hassette_for_db: MagicMock,
        retention_service: DatabaseService,
    ) -> None:
        """blocking_events (priority 2) drains after framework executions (1) and before
        app executions (3) / log_records (4).
        """
        now = time.time()
        for i in range(3):
            await insert_blocking_event(db, now - i)
        await insert_tiered_execution(db, now - 10, SOURCE_TIER_APP)
        await db.commit()

        # Call sites of get_live_data_size_mb(): 1 = entry check, then one per delete batch that
        # removed rows, and one at the end of each priority tier.
        calls = 0

        async def mock_size() -> float:
            nonlocal calls
            calls += 1
            # Over limit through the entry check and the framework-tier pass (no rows there);
            # under limit once blocking_events' first batch has been deleted.
            return 10.0 if calls <= 2 else 0.0

        await run_size_failsafe(retention_service, mock_hassette_for_db, live_size=mock_size)

        assert await count_rows(db, "blocking_events") == 0  # drained at priority 2

        assert await count_rows(db, "executions", source_tier="app") == 1  # priority 3 never reached
