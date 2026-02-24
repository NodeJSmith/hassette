"""Integration tests for DatabaseService with real SQLite."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from hassette.core.database_service import DatabaseService


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config pointing to tmp_path."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
def service(mock_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance (not yet initialized)."""
    return DatabaseService.create(mock_hassette)


@pytest.fixture
async def initialized_service(service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize a DatabaseService and clean up after the test."""
    await service.on_initialize()
    try:
        yield service
    finally:
        if service._db is not None:
            await service._db.close()
            service._db = None


def _get_tables(db_path: Path) -> list[str]:
    """Helper: return user-defined table names from the database."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        return sorted(row[0] for row in cursor.fetchall())
    finally:
        conn.close()


def _get_indexes(db_path: Path) -> list[str]:
    """Helper: return index names from the database."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        return sorted(row[0] for row in cursor.fetchall())
    finally:
        conn.close()


async def test_fresh_db_creates_all_tables(initialized_service: DatabaseService) -> None:
    """on_initialize creates all 5 tables and 8 indexes on a fresh database."""
    db_path = initialized_service._db_path
    tables = _get_tables(db_path)
    assert tables == ["handler_invocations", "job_executions", "listeners", "scheduled_jobs", "sessions"]

    indexes = _get_indexes(db_path)
    assert len(indexes) == 8
    assert "idx_hi_listener_time" in indexes
    assert "idx_hi_status_time" in indexes
    assert "idx_hi_time" in indexes
    assert "idx_hi_session" in indexes
    assert "idx_je_job_time" in indexes
    assert "idx_je_status_time" in indexes
    assert "idx_je_time" in indexes
    assert "idx_je_session" in indexes


async def test_migration_idempotency(service: DatabaseService) -> None:
    """Running migrations twice on the same database does not error."""
    await service.on_initialize()
    try:
        session_id_1 = service.session_id

        # Close and re-initialize on same database
        await service._db.close()  # type: ignore[union-attr]
        service._db = None
        service._session_id = None

        await service.on_initialize()
        session_id_2 = service.session_id

        # Second session should have a different ID
        assert session_id_2 != session_id_1
        assert session_id_2 > session_id_1
    finally:
        if service._db:
            await service._db.close()
            service._db = None


async def test_session_lifecycle(service: DatabaseService) -> None:
    """on_initialize creates a running session; on_shutdown marks it success."""
    await service.on_initialize()
    try:
        session_id = service.session_id

        # Verify session is running
        cursor = await service.db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "running"
        assert row[1] is None  # stopped_at is NULL while running

        db_path = service._db_path
        await service.on_shutdown()

        # Verify via direct connection since service closed its connection
        conn = sqlite3.connect(db_path)
        try:
            cursor_sync = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,))
            row = cursor_sync.fetchone()
            assert row is not None
            assert row[0] == "success"
            assert row[1] is not None  # stopped_at is set
        finally:
            conn.close()
    except Exception:
        if service._db:
            await service._db.close()
            service._db = None
        raise


async def test_orphan_recovery(service: DatabaseService) -> None:
    """On startup, sessions left in 'running' are marked 'unknown'."""
    # First init creates a running session
    await service.on_initialize()
    first_session_id = service.session_id
    heartbeat_ts = time.time() - 600  # 10 minutes ago

    # Simulate a crash: update heartbeat and leave session as 'running'
    await service.db.execute("UPDATE sessions SET last_heartbeat_at = ? WHERE id = ?", (heartbeat_ts, first_session_id))
    await service.db.commit()
    await service._db.close()  # type: ignore[union-attr]
    service._db = None
    service._session_id = None

    # Re-initialize — should mark first session as 'unknown'
    await service.on_initialize()
    try:
        cursor = await service.db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (first_session_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "unknown"
        assert row[1] == pytest.approx(heartbeat_ts, abs=1)

        # New session should be running
        assert service.session_id != first_session_id
        cursor = await service.db.execute("SELECT status FROM sessions WHERE id = ?", (service.session_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "running"
    finally:
        if service._db:
            await service._db.close()
            service._db = None


async def test_pragmas_are_set(initialized_service: DatabaseService) -> None:
    """PRAGMAs are configured after connection."""
    cursor = await initialized_service.db.execute("PRAGMA journal_mode")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "wal"

    cursor = await initialized_service.db.execute("PRAGMA synchronous")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1  # NORMAL = 1

    cursor = await initialized_service.db.execute("PRAGMA busy_timeout")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 5000

    cursor = await initialized_service.db.execute("PRAGMA foreign_keys")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_heartbeat_update(initialized_service: DatabaseService) -> None:
    """_update_heartbeat updates last_heartbeat_at."""
    cursor = await initialized_service.db.execute(
        "SELECT last_heartbeat_at FROM sessions WHERE id = ?", (initialized_service.session_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    initial_heartbeat = row[0]

    await asyncio.sleep(0.05)
    await initialized_service._update_heartbeat()

    cursor = await initialized_service.db.execute(
        "SELECT last_heartbeat_at FROM sessions WHERE id = ?", (initialized_service.session_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_retention_cleanup(initialized_service: DatabaseService) -> None:
    """_run_retention_cleanup deletes old records but keeps recent ones."""
    session_id = initialized_service.session_id
    db = initialized_service.db

    # Insert a listener for FK reference
    await db.execute(
        "INSERT INTO listeners (app_key, instance_index, handler_method, topic, source_location, "
        "first_registered_at, last_registered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test.App", 0, "on_event", "state_changed", "test.py:1", time.time(), time.time()),
    )
    await db.commit()

    # Insert a scheduled_job for FK reference
    await db.execute(
        "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location, "
        "first_registered_at, last_registered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("test.App", 0, "my_job", "run_job", "test.py:2", time.time(), time.time()),
    )
    await db.commit()

    now = time.time()
    old_ts = now - (8 * 86400)  # 8 days ago (beyond 7-day retention)
    recent_ts = now - (1 * 86400)  # 1 day ago (within retention)

    # Insert old and recent handler_invocations
    await db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
        "VALUES (1, ?, ?, 10.0, 'success')",
        (session_id, old_ts),
    )
    await db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
        "VALUES (1, ?, ?, 10.0, 'success')",
        (session_id, recent_ts),
    )

    # Insert old and recent job_executions
    await db.execute(
        "INSERT INTO job_executions (job_id, session_id, execution_start_ts, duration_ms, status) "
        "VALUES (1, ?, ?, 5.0, 'success')",
        (session_id, old_ts),
    )
    await db.execute(
        "INSERT INTO job_executions (job_id, session_id, execution_start_ts, duration_ms, status) "
        "VALUES (1, ?, ?, 5.0, 'success')",
        (session_id, recent_ts),
    )
    await db.commit()

    await initialized_service._run_retention_cleanup()

    # Old records should be deleted, recent ones retained
    cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1

    cursor = await db.execute("SELECT COUNT(*) FROM job_executions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_serve_exits_on_shutdown(initialized_service: DatabaseService) -> None:
    """serve() exits when the shutdown event is set."""

    async def set_shutdown() -> None:
        await asyncio.sleep(0.1)
        initialized_service.shutdown_event.set()

    shutdown_task = asyncio.create_task(set_shutdown())

    await asyncio.wait_for(initialized_service.serve(), timeout=5.0)
    await shutdown_task

    assert initialized_service.is_ready() is False


async def test_serve_runs_heartbeat_and_retention(initialized_service: DatabaseService) -> None:
    """serve() updates heartbeat and runs retention cleanup during the loop."""
    # Get initial heartbeat
    cursor = await initialized_service.db.execute(
        "SELECT last_heartbeat_at FROM sessions WHERE id = ?", (initialized_service.session_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    initial_heartbeat = row[0]

    async def shutdown_after_loop() -> None:
        # Wait for at least one heartbeat cycle
        await asyncio.sleep(0.3)
        initialized_service.shutdown_event.set()

    shutdown_task = asyncio.create_task(shutdown_after_loop())

    # Patch intervals to very small values so the loop iterates quickly
    with (
        patch("hassette.core.database_service._HEARTBEAT_INTERVAL_SECONDS", 0.1),
        patch("hassette.core.database_service._RETENTION_INTERVAL_SECONDS", 0.1),
    ):
        await asyncio.wait_for(initialized_service.serve(), timeout=5.0)

    await shutdown_task

    # Heartbeat should have been updated
    cursor = await initialized_service.db.execute(
        "SELECT last_heartbeat_at FROM sessions WHERE id = ?", (initialized_service.session_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_heartbeat_failure_tracking_marks_not_ready(initialized_service: DatabaseService) -> None:
    """After MAX consecutive heartbeat failures, service is marked not-ready."""
    assert initialized_service._consecutive_heartbeat_failures == 0

    # Service must be marked ready first so we can observe the transition
    initialized_service.mark_ready(reason="test setup")
    assert initialized_service.is_ready() is True

    # Close the DB to force heartbeat failures
    await initialized_service._db.close()  # type: ignore[union-attr]

    # First two failures should NOT mark not-ready
    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 1
    assert initialized_service.is_ready() is True

    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 2
    assert initialized_service.is_ready() is True

    # Third failure should trigger mark_not_ready
    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 3
    assert initialized_service.is_ready() is False

    # Restore a valid connection and verify recovery resets counter
    initialized_service._db = await aiosqlite.connect(initialized_service._db_path)
    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_heartbeat_recovery_resets_counter(initialized_service: DatabaseService) -> None:
    """A successful heartbeat after failures resets the failure counter."""
    # Simulate one failure by temporarily breaking the connection
    real_db = initialized_service._db
    initialized_service._db = MagicMock()
    initialized_service._db.execute = AsyncMock(side_effect=Exception("db error"))

    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 1

    # Restore real connection — next heartbeat should succeed and reset
    initialized_service._db = real_db
    await initialized_service._update_heartbeat()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_db_property_works_after_init(initialized_service: DatabaseService) -> None:
    """db property returns the connection after initialization."""
    conn = initialized_service.db
    assert conn is not None

    cursor = await conn.execute("SELECT 1")
    row = await cursor.fetchone()
    assert row == (1,)


async def test_session_id_property_works_after_init(initialized_service: DatabaseService) -> None:
    """session_id property returns the ID after initialization."""
    sid = initialized_service.session_id
    assert isinstance(sid, int)
    assert sid > 0
