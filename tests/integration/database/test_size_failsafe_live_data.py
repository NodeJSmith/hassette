"""Live-data size failsafe and free-page reclaim, against a real SQLite database."""

import time
from pathlib import Path

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import database_failsafe
from hassette.core.database_failsafe import WalCheckpointBlockedError, truncate_wal
from hassette.core.database_service import DatabaseService
from hassette.core.database_sql import get_freelist_count, get_live_data_mb, run_incremental_vacuum
from tests.integration.database.conftest import seed_app_executions
from tests.support.helpers import SIZE_FAILSAFE_TRIGGER_MB, seed_listener_for_fk
from tests.support.sql import count_rows, sqlite_disk_bytes

FILLER_ROWS = 3000
"""Rows of ~4 KiB filler -- dropping them leaves a free list of a few thousand pages."""

LARGE_ROWS = 2000
"""Executions of ~2 KiB each -- a few MiB of live data, enough for batched deletes to matter."""


async def create_free_pages(db: aiosqlite.Connection) -> int:
    """Grow the file with a filler table, drop it, and checkpoint; return the free page count."""
    await db.execute("CREATE TABLE filler (b BLOB)")
    await db.executemany("INSERT INTO filler (b) VALUES (zeroblob(4000))", [()] * FILLER_ROWS)
    await db.execute("DROP TABLE filler")
    cursor = await db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await cursor.fetchall()
    await cursor.close()
    return await get_freelist_count(db)


def file_size_mb(service: DatabaseService) -> float:
    """On-disk size (main file + WAL + SHM) in MB."""
    return sqlite_disk_bytes(service._db_path) / (1024 * 1024)  # pyright: ignore[reportPrivateUsage]


async def limit_between_live_and_file_size(service: DatabaseService) -> float:
    """A size limit live data fits under, which the file exceeds until half its free pages are gone."""
    live_mb = await get_live_data_mb(service.db)
    return live_mb + (file_size_mb(service) - live_mb) / 2


async def seed_large_executions(service: DatabaseService) -> None:
    db = service.db
    await seed_listener_for_fk(db)
    now = time.time()
    await db.executemany(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,"
        " error_message) VALUES ('handler', 1, ?, ?, 10.0, 'error', ?)",
        [(service.hassette.session_id, now + i, "x" * 2000) for i in range(LARGE_ROWS)],
    )
    await db.commit()


async def raise_reclaim_failure(_db: aiosqlite.Connection) -> None:
    raise aiosqlite.OperationalError("simulated reclaim failure")


async def switch_to_auto_vacuum_none(db: aiosqlite.Connection) -> None:
    """Rebuild the file in ``auto_vacuum = NONE``, the mode of databases created before incremental vacuum."""
    await db.execute("PRAGMA auto_vacuum = NONE")
    await db.execute("VACUUM")
    cursor = await db.execute("PRAGMA auto_vacuum")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_run_incremental_vacuum_frees_requested_pages(initialized_service: DatabaseService) -> None:
    """incremental_vacuum(N) frees N pages, not just the one freed before its first result row."""
    db = initialized_service.db
    free_before = await create_free_pages(db)
    assert free_before > 100

    await run_incremental_vacuum(db, 100)

    assert await get_freelist_count(db) == free_before - 100


async def test_size_failsafe_deletes_nothing_when_oversized_only_by_free_pages(
    initialized_service: DatabaseService,
) -> None:
    """A file over the limit only because of free pages loses no rows: live data is what's limited."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    await create_free_pages(db)
    max_size_mb = await limit_between_live_and_file_size(initialized_service)
    assert file_size_mb(initialized_service) > max_size_mb
    initialized_service.hassette.config.database.max_size_mb = max_size_mb

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "executions") == 10


async def test_size_failsafe_deletes_nothing_in_auto_vacuum_none_with_large_free_list(
    initialized_service: DatabaseService,
) -> None:
    """A database whose free pages can't be reclaimed (``auto_vacuum = NONE``) is judged on live data too."""
    db = initialized_service.db
    await switch_to_auto_vacuum_none(db)
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    free_pages = await create_free_pages(db)
    assert free_pages > 100
    max_size_mb = await limit_between_live_and_file_size(initialized_service)
    assert file_size_mb(initialized_service) > max_size_mb
    initialized_service.hassette.config.database.max_size_mb = max_size_mb

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "executions") == 10
    assert await get_freelist_count(db) == free_pages


async def test_size_failsafe_deletes_until_live_data_fits_then_shrinks_file(
    initialized_service: DatabaseService,
) -> None:
    """Live data over the limit: rows go until live data fits, then the file shrinks to match."""
    db = initialized_service.db
    config = initialized_service.hassette.config.database
    config.size_failsafe_delete_batch = 100
    config.size_failsafe_max_iterations = 1000
    await seed_large_executions(initialized_service)
    live_before = await get_live_data_mb(db)
    file_before = file_size_mb(initialized_service)
    config.max_size_mb = live_before / 2

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    remaining = await count_rows(db, "executions")
    assert 0 < remaining < LARGE_ROWS
    assert await get_live_data_mb(db) <= config.max_size_mb
    assert await get_freelist_count(db) == 0
    assert file_size_mb(initialized_service) < file_before


async def test_size_failsafe_still_deletes_when_reclaim_fails(
    initialized_service: DatabaseService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing post-delete reclaim is best-effort: the deletes stand and nothing is raised."""
    monkeypatch.setattr(database_failsafe, "reclaim_free_pages", raise_reclaim_failure)
    config = initialized_service.hassette.config.database
    await seed_large_executions(initialized_service)
    config.max_size_mb = await get_live_data_mb(initialized_service.db) / 2

    await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(initialized_service.db, "executions") < LARGE_ROWS


async def test_size_failsafe_deletes_when_wal_is_blocked_and_live_data_exceeds_limit(
    initialized_service: DatabaseService,
) -> None:
    """A reader blocking WAL truncation doesn't stop deletes when live data alone is over the limit."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB
    reader = initialized_service._read_db  # pyright: ignore[reportPrivateUsage]
    assert reader is not None
    await reader.execute("BEGIN")
    cursor = await reader.execute("SELECT COUNT(*) FROM executions")
    await cursor.fetchall()
    try:
        await initialized_service._check_size_failsafe()  # pyright: ignore[reportPrivateUsage]
        # A completed TRUNCATE checkpoint leaves a zero-byte WAL, so a non-empty one proves the block.
        wal_path = Path(f"{initialized_service._db_path}-wal")  # pyright: ignore[reportPrivateUsage]
        assert wal_path.stat().st_size > 0  # noqa: ASYNC240
    finally:
        await reader.execute("COMMIT")

    assert await count_rows(db, "executions") < 10


async def test_truncate_wal_raises_when_a_reader_blocks_the_checkpoint(initialized_service: DatabaseService) -> None:
    """A blocked wal_checkpoint(TRUNCATE) returns a busy row instead of raising; truncate_wal turns it into an error."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    await seed_app_executions(db, initialized_service.hassette.session_id)
    reader = initialized_service._read_db  # pyright: ignore[reportPrivateUsage]
    assert reader is not None
    await reader.execute("BEGIN")
    cursor = await reader.execute("SELECT COUNT(*) FROM executions")
    await cursor.fetchall()
    try:
        await db.execute("DELETE FROM executions")
        with pytest.raises(WalCheckpointBlockedError):
            await truncate_wal(db)
    finally:
        await reader.execute("COMMIT")


async def test_retention_cleanup_reclaims_freed_pages(initialized_service: DatabaseService) -> None:
    """Retention leaves no free list behind after deleting a large batch of old rows."""
    db = initialized_service.db
    await seed_listener_for_fk(db)
    old_ts = time.time() - 31 * SECONDS_PER_DAY
    await db.executemany(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status,"
        " error_message) VALUES ('handler', 1, ?, ?, 10.0, 'error', ?)",
        [(initialized_service.hassette.session_id, old_ts + i, "x" * 2000) for i in range(2000)],
    )
    await db.commit()

    await initialized_service._do_run_retention_cleanup()  # pyright: ignore[reportPrivateUsage]

    assert await count_rows(db, "executions") == 0
    assert await get_freelist_count(db) == 0
