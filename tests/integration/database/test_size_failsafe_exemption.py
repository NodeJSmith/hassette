"""The size failsafe's handling of ``log_records`` against a real SQLite database: DEBUG lines are
deleted first, INFO and above are ``failsafe_exempt``.
"""

import time
from typing import Any
from unittest.mock import AsyncMock

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService
from tests.support.helpers import SIZE_FAILSAFE_TRIGGER_MB, seed_listener_for_fk
from tests.support.sql import count_rows

ALWAYS_OVER_LIMIT_MB = 10.0
NON_DEBUG_LEVELS = ("INFO", "WARNING", "ERROR", "CRITICAL")


async def seed_executions(db: aiosqlite.Connection, session_id: int, n: int, now: float) -> None:
    await seed_listener_for_fk(db)
    for i in range(n):
        await db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,"
            " source_tier) VALUES ('handler', 1, ?, ?, 10.0, 'success', ?)",
            (session_id, now - (100 - i), "framework" if i % 2 else "app"),
        )


async def seed_logs(db: aiosqlite.Connection, levels: list[str], oldest_ts: float) -> None:
    """Insert one log line per entry in ``levels``, one second apart starting at ``oldest_ts``."""
    for i, level in enumerate(levels):
        await db.execute(
            "INSERT INTO log_records (seq, timestamp, level, logger_name, message) VALUES (?, ?, ?, 'test', 'hello')",
            (i, oldest_ts + i, level),
        )


async def test_size_failsafe_leaves_info_and_above_log_records_untouched(initialized_service: DatabaseService) -> None:
    """INFO and above are exempt from the size failsafe: it drains executions, blocking_events and
    DEBUG lines down to nothing while the DB is over the limit, but never deletes another log line.
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    now = time.time()
    await seed_executions(db, session_id, 10, now)
    for i in range(10):
        await db.execute(
            "INSERT INTO blocking_events (session_id, tier, detected_ts, source_tier)"
            " VALUES (?, 'monkeypatch', ?, 'app')",
            (session_id, now - (100 - i)),
        )
    # Deliberately the oldest rows in the database — an unexempt failsafe would delete these first
    # within their own tier, so surviving is not an artifact of recency.
    non_debug = list(NON_DEBUG_LEVELS) * 2
    await seed_logs(db, [*non_debug, "DEBUG", "DEBUG"], now - 2000)
    await db.commit()

    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    # Every failsafe-managed tier drained (the DB stays over this tiny limit regardless).
    assert await count_rows(db, "executions") == 0
    assert await count_rows(db, "blocking_events") == 0
    assert await count_rows(db, "log_records", level="DEBUG") == 0
    # ...but every INFO-and-above line is intact.
    assert await count_rows(db, "log_records") == len(non_debug)


async def test_size_failsafe_deletes_debug_lines_before_executions(initialized_service: DatabaseService) -> None:
    """DEBUG lines are the first tier: when deleting them brings live data under the limit, no
    execution is touched, even executions older than every DEBUG line.
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db
    now = time.time()
    await seed_executions(db, session_id, 4, now - 10_000)
    await seed_logs(db, ["DEBUG"] * 5, now - 50)
    await db.commit()

    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    # Over the limit at the entry check, under it after the DEBUG tier's first batch.
    initialized_service.get_live_data_size_mb = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        side_effect=[ALWAYS_OVER_LIMIT_MB, 0.0, 0.0]
    )

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "log_records") == 0
    assert await count_rows(db, "executions") == 4


async def test_capped_debug_tier_stops_the_run_before_executions(initialized_service: DatabaseService) -> None:
    """The DEBUG tier spends the shared budget like any other tier; when it runs out with DEBUG lines
    left, the run stops there and executions are protected until the next cycle.
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db
    now = time.time()
    await seed_executions(db, session_id, 4, now - 10_000)
    await seed_logs(db, ["DEBUG"] * 5, now - 50)
    await db.commit()

    config = initialized_service.hassette.config.database
    config.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    config.size_failsafe_max_iterations = 1
    config.size_failsafe_delete_batch = 2
    initialized_service.get_live_data_size_mb = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        return_value=ALWAYS_OVER_LIMIT_MB
    )

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "log_records") == 3  # one batch of 2, then capped
    assert await count_rows(db, "executions") == 4


async def test_debug_tier_queries_use_the_partial_index(
    initialized_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failsafe's own DEBUG delete and stale-row probe read migration 022's partial index rather
    than walking idx_lr_time past every INFO-and-above line.
    """
    db = initialized_service.db
    await seed_logs(db, ["DEBUG"] * 3, time.time() - 50)
    await db.commit()

    config = initialized_service.hassette.config.database
    config.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    # One full batch with rows left over sends the tier through the stale-row probe too.
    config.size_failsafe_max_iterations = 1
    config.size_failsafe_delete_batch = 2
    initialized_service.get_live_data_size_mb = AsyncMock(  # pyright: ignore[reportAttributeAccessIssue]
        return_value=ALWAYS_OVER_LIMIT_MB
    )

    captured: list[tuple[str, list[Any]]] = []
    original_execute = db.execute

    async def capturing_execute(sql: str, params: Any = None) -> Any:
        if "FROM log_records" in sql and params and "DEBUG" in params:
            captured.append((sql, list(params)))
        return await original_execute(sql, params)

    monkeypatch.setattr(db, "execute", capturing_execute)
    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.undo()

    assert any(sql.lstrip().startswith("DELETE") for sql, _ in captured)
    assert any(sql.lstrip().startswith("SELECT 1") for sql, _ in captured)
    for sql, params in captured:
        cursor = await db.execute(f"EXPLAIN QUERY PLAN {sql}", params)
        plan = [row[3] for row in await cursor.fetchall()]
        assert any("idx_lr_debug_time" in step for step in plan), (sql, plan)
