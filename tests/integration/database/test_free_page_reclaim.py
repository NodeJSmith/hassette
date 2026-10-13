"""Free-page reclaim in the size failsafe and retention cleanup, against a real SQLite database."""

import time

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import database_failsafe, database_sql
from hassette.core.database_service import DatabaseService
from hassette.core.database_sql import get_freelist_count, get_live_data_mb, run_incremental_vacuum
from tests.integration.database.conftest import seed_app_executions
from tests.support.helpers import seed_listener_for_fk

FILLER_ROWS = 3000
"""Rows of ~4 KiB filler -- dropping them leaves a free list of a few thousand pages."""


async def create_free_pages(db: aiosqlite.Connection) -> int:
    """Grow the file with a filler table, drop it, and checkpoint; return the free page count."""
    await db.execute("CREATE TABLE filler (b BLOB)")
    await db.executemany("INSERT INTO filler (b) VALUES (zeroblob(4000))", [()] * FILLER_ROWS)
    await db.execute("DROP TABLE filler")
    cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await cursor.fetchall()
    await cursor.close()
    return await get_freelist_count(db)


async def live_mb_plus_half_free(service: DatabaseService) -> float:
    """A size limit live data fits under, which the file exceeds until half its free pages are gone."""
    live_mb = await get_live_data_mb(service.db)
    return live_mb + (service.get_db_size_mb() - live_mb) / 2


async def count_executions(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    return row[0]


async def test_run_incremental_vacuum_frees_requested_pages(initialized_service: DatabaseService) -> None:
    """incremental_vacuum(N) frees N pages, not just the one freed before its first result row."""
    db = initialized_service.db
    free_before = await create_free_pages(db)
    assert free_before > 100

    await run_incremental_vacuum(db, 100)

    assert await get_freelist_count(db) == free_before - 100


async def test_size_failsafe_reclaims_free_pages_without_deleting_rows(initialized_service: DatabaseService) -> None:
    """A database over the limit only because of free pages gets back under it with no rows deleted."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    free_pages = await create_free_pages(db)

    cursor = await db.execute("PRAGMA page_size")
    row = await cursor.fetchone()
    assert row is not None
    free_mb = free_pages * row[0] / (1024 * 1024)
    max_size_mb = initialized_service.get_db_size_mb() - free_mb / 2
    initialized_service.hassette.config.database.max_size_mb = max_size_mb

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_executions(db) == 10
    assert await get_freelist_count(db) == 0
    assert initialized_service.get_db_size_mb() <= max_size_mb


async def test_size_failsafe_deletes_nothing_while_free_pages_remain(
    initialized_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the reclaim runs out of time with free pages left, the cycle deletes no rows.

    A zero budget still runs one chunk -- the deadline is checked after each chunk -- so the
    reclaim makes 10 pages of progress and then stops.
    """
    monkeypatch.setattr(database_sql, "FREE_PAGE_RECLAIM_CHUNK_PAGES", 10)
    monkeypatch.setattr(database_sql, "FREE_PAGE_RECLAIM_BUDGET_SECONDS", 0.0)
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    free_pages = await create_free_pages(db)
    # Over the limit only because of free pages: live data alone fits under it.
    initialized_service.hassette.config.database.max_size_mb = await live_mb_plus_half_free(initialized_service)

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_executions(db) == 10
    assert 0 < await get_freelist_count(db) < free_pages


async def raise_reclaim_failure(_db: aiosqlite.Connection) -> None:
    raise aiosqlite.OperationalError("simulated reclaim failure")


async def test_size_failsafe_deletes_nothing_when_reclaim_fails_and_live_data_fits(
    initialized_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed reclaim defers deletes while live data alone is under the limit."""
    monkeypatch.setattr(database_failsafe, "reclaim_free_pages", raise_reclaim_failure)
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    await create_free_pages(db)
    initialized_service.hassette.config.database.max_size_mb = await live_mb_plus_half_free(initialized_service)

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_executions(db) == 10


async def test_size_failsafe_deletes_when_wal_is_blocked_and_live_data_exceeds_limit(
    initialized_service: DatabaseService,
) -> None:
    """A reader blocking WAL truncation doesn't stop deletes when live data alone is over the limit."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    # Far below what even an empty database occupies.
    initialized_service.hassette.config.database.max_size_mb = 0.0001
    reader = initialized_service._read_db  # pyright: ignore[reportPrivateUsage]
    assert reader is not None
    await reader.execute("BEGIN")
    cursor = await reader.execute("SELECT COUNT(*) FROM executions")
    await cursor.fetchall()
    try:
        await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
    finally:
        await reader.execute("COMMIT")

    assert await count_executions(db) < 10


async def test_retention_cleanup_reclaims_freed_pages(initialized_service: DatabaseService) -> None:
    """Retention leaves no free list behind after deleting a large batch of old rows."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    old_ts = time.time() - 30 * SECONDS_PER_DAY
    await db.executemany(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,"
        " error_message) VALUES ('handler', 1, ?, ?, 10.0, 'error', ?)",
        [(initialized_service.hassette.session_id, old_ts + i, "x" * 2000) for i in range(2000)],
    )
    await db.commit()

    await initialized_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

    assert await count_executions(db) == 0
    assert await get_freelist_count(db) == 0
