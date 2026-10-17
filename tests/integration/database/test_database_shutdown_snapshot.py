"""DatabaseService writes database.shutdown_snapshot_path on shutdown, after draining its write queue."""

import asyncio
import sqlite3
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from hassette.core.database_service import DatabaseService
from tests.support.helpers import (
    DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS,
    DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
)
from tests.support.mock_hassette import make_mock_hassette


def build_service(tmp_path: Path, snapshot_path: Path | None) -> DatabaseService:
    hassette = make_mock_hassette(
        data_dir=tmp_path,
        set_ready=False,
        database={
            "telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
            "shutdown_snapshot_path": snapshot_path,
        },
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
    )
    return DatabaseService(hassette, parent=None)


def insert_session(service: DatabaseService) -> Coroutine[Any, Any, None]:
    async def write() -> None:
        await service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (1, 1, 'running')"
        )
        await service.db.commit()

    return write()


def session_count(path: Path) -> int:
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT count(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()


async def test_shutdown_writes_the_snapshot_with_drained_writes(tmp_path: Path) -> None:
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"
    service = build_service(tmp_path, snapshot)
    await service.on_initialize()
    await service.submit(insert_session(service))  # the worker is now running
    # Fire-and-forget: the snapshot can only hold this row if shutdown drained the queue before writing it.
    service.enqueue(insert_session(service))

    await service.on_shutdown()

    assert session_count(snapshot) == 2


async def test_shutdown_without_the_setting_writes_no_snapshot(tmp_path: Path) -> None:
    service = build_service(tmp_path, None)
    await service.on_initialize()

    await service.on_shutdown()

    names = await asyncio.to_thread(lambda: {path.name for path in tmp_path.iterdir()})
    assert names <= {"hassette.db", "hassette.db-wal", "hassette.db-shm"}, names


async def test_failed_shutdown_snapshot_does_not_fail_shutdown(tmp_path: Path) -> None:
    """A snapshot that can't be written is logged; shutdown finishes and the connections still close."""
    snapshot = tmp_path / "blocked"
    snapshot.mkdir()  # a directory where the snapshot file should go, so the rename fails
    service = build_service(tmp_path, snapshot)
    await service.on_initialize()

    await service.on_shutdown()

    assert snapshot.is_dir()
    assert not service.is_db_ready


async def test_shutdown_snapshot_skips_a_database_that_was_never_opened(tmp_path: Path) -> None:
    """A service whose initialization never ran has no database file, so nothing is written."""
    snapshot = tmp_path / "backup" / "hassette-snapshot.db"
    service = build_service(tmp_path, snapshot)

    await service.write_shutdown_snapshot()

    assert not await asyncio.to_thread(snapshot.exists)
