"""Integration tests for DatabaseService with real SQLite."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core.database_service import DatabaseService
from hassette.test_utils.config import TEST_SOURCE_LOCATION
from hassette.test_utils.mock_hassette import make_mock_hassette


@pytest.fixture
def mock_hassette_fresh(tmp_path: Path) -> AsyncMock:
    """Create a mock Hassette with a fresh (empty) data_dir for migration-from-scratch tests."""
    return make_mock_hassette(
        sealed=False,
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": 500},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
    )


@pytest.fixture
def service(db_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance (not yet initialized)."""
    return DatabaseService(db_hassette, parent=None)


@pytest.fixture
def fresh_service(mock_hassette_fresh: MagicMock) -> DatabaseService:
    """Create a DatabaseService against a fresh (empty) data_dir — no pre-migrated DB."""
    return DatabaseService(mock_hassette_fresh, parent=None)


@pytest.fixture
async def initialized_fresh_service(fresh_service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize a DatabaseService from scratch (runs real migrations) with a seeded session."""
    await fresh_service.on_initialize()
    try:
        now = time.time()
        cursor = await fresh_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        fresh_service.hassette.session_id = cursor.lastrowid
        await fresh_service.db.commit()
        yield fresh_service
    finally:
        await fresh_service.on_shutdown()


@pytest.fixture
async def initialized_service(service: DatabaseService) -> AsyncIterator[DatabaseService]:
    """Initialize a DatabaseService and create a session row for heartbeat tests."""
    await service.on_initialize()
    try:
        # Manually create a session row so heartbeat/retention tests have a valid session_id
        now = time.time()
        cursor = await service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (now, now),
        )
        service.hassette.session_id = cursor.lastrowid
        await service.db.commit()
        yield service
    finally:
        await service.on_shutdown()


async def test_fresh_db_creates_all_tables(initialized_fresh_service: DatabaseService) -> None:
    """on_initialize creates all tables and indexes on a fresh database."""
    db_path = initialized_fresh_service._db_path
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        assert tables == [
            "handler_invocations",
            "job_executions",
            "listeners",
            "log_records",
            "scheduled_jobs",
            "sessions",
        ]

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = sorted(row[0] for row in cursor.fetchall())
        # 14 original idx_ indexes + 3 new idx_lr_ indexes + 2 new perf indexes = 19
        assert len(indexes) == 19
        assert "idx_hi_listener_time" in indexes
        assert "idx_hi_listener_status_time" in indexes
        assert "idx_hi_status_time" in indexes
        assert "idx_hi_time" in indexes
        assert "idx_hi_session" in indexes
        assert "idx_je_job_time" in indexes
        assert "idx_je_job_status_time" in indexes
        assert "idx_je_status_time" in indexes
        assert "idx_je_time" in indexes
        assert "idx_je_session" in indexes
        assert "idx_listeners_app" in indexes
        assert "idx_listeners_natural" in indexes
        assert "idx_scheduled_jobs_app" in indexes
        assert "idx_scheduled_jobs_natural" in indexes
        assert "idx_lr_time" in indexes
        assert "idx_lr_exec" in indexes
        assert "idx_lr_app_time" in indexes

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%'")
        unique_indexes = sorted(row[0] for row in cursor.fetchall())
        assert "uq_hi_execution_id" in unique_indexes
        assert "uq_je_execution_id" in unique_indexes
    finally:
        conn.close()


async def test_migration_idempotency(service: DatabaseService) -> None:
    """Running migrations twice on the same database does not error."""
    await service.on_initialize()
    try:
        # Verify DB is connected
        cursor = await service.db.execute("SELECT 1")
        row = await cursor.fetchone()
        assert row[0] == 1

        # Tear down the first init cleanly before re-initializing
        await service.on_shutdown()

        await service.on_initialize()

        # Verify DB reconnected successfully
        cursor = await service.db.execute("SELECT 1")
        row = await cursor.fetchone()
        assert row[0] == 1
    finally:
        await service.on_shutdown()


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
    session_id = initialized_service.hassette.session_id
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    initial_heartbeat = row[0]

    await asyncio.sleep(0.05)
    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()

    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_retention_cleanup(initialized_service: DatabaseService) -> None:
    """_run_retention_cleanup deletes old records but keeps recent ones."""
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    # Insert a listener for FK reference
    await db.execute(
        "INSERT INTO listeners (app_key, instance_index, handler_method, topic, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "on_event", "state_changed", TEST_SOURCE_LOCATION),
    )
    await db.commit()

    # Insert a scheduled_job for FK reference
    await db.execute(
        "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "my_job", "run_job", "test.py:2"),
    )
    await db.commit()

    now = time.time()
    old_ts = now - (8 * SECONDS_PER_DAY)  # 8 days ago (beyond 7-day retention)
    recent_ts = now - (1 * SECONDS_PER_DAY)  # 1 day ago (within retention)

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

    await initialized_service._db_write_queue.join()

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
    session_id = initialized_service.hassette.session_id
    # Get initial heartbeat
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
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

    await initialized_service._db_write_queue.join()

    # Heartbeat should have been updated
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_heartbeat_failure_counter_tracks_failures(initialized_service: DatabaseService) -> None:
    """Heartbeat failures increment counter; recovery resets it."""
    assert initialized_service._consecutive_heartbeat_failures == 0

    # Close the DB to force heartbeat failures
    assert initialized_service._db is not None
    await initialized_service._db.close()

    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 2

    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 3

    # Restore a valid connection and verify recovery resets counter
    initialized_service._db = await aiosqlite.connect(initialized_service._db_path)
    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_heartbeat_recovery_resets_counter(initialized_service: DatabaseService) -> None:
    """A successful heartbeat after failures resets the failure counter."""
    # Simulate one failure by temporarily breaking the connection
    real_db = initialized_service._db
    initialized_service._db = MagicMock()
    initialized_service._db.execute = AsyncMock(side_effect=sqlite3.OperationalError("db error"))

    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    # Restore real connection — next heartbeat should succeed and reset
    initialized_service._db = real_db
    await initialized_service._update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_db_property_works_after_init(initialized_service: DatabaseService) -> None:
    """db property returns the connection after initialization."""
    conn = initialized_service.db
    assert conn is not None

    cursor = await conn.execute("SELECT 1")
    row = await cursor.fetchone()
    assert row[0] == 1


async def test_serve_raises_after_max_heartbeat_failures(initialized_service: DatabaseService) -> None:
    """serve() raises RuntimeError after MAX consecutive heartbeat failures."""
    # Close DB to force failures
    assert initialized_service._db is not None
    await initialized_service._db.close()

    with (
        patch("hassette.core.database_service._HEARTBEAT_INTERVAL_SECONDS", 0.01),
        pytest.raises(RuntimeError, match="Heartbeat failed 3 consecutive times"),
    ):
        await asyncio.wait_for(initialized_service.serve(), timeout=5.0)


async def test_drain_on_shutdown(service: DatabaseService) -> None:
    """on_shutdown() blocks until all queued coroutines complete before closing the connection."""
    await service.on_initialize()

    completed: list[int] = []
    gates: list[asyncio.Event] = [asyncio.Event() for _ in range(3)]

    async def slow_coro(index: int) -> None:
        await gates[index].wait()
        completed.append(index)

    # Enqueue three slow coroutines before unblocking any of them
    service.enqueue(slow_coro(0))
    service.enqueue(slow_coro(1))
    service.enqueue(slow_coro(2))

    # on_shutdown() must not return until all three are done
    async def release_gates_then_shutdown() -> None:
        # Give the worker a moment to pick up the first item
        await asyncio.sleep(0)
        # Release gates one by one to simulate sequential slow writes
        for gate in gates:
            gate.set()
            await asyncio.sleep(0)
        await service.on_shutdown()

    await asyncio.wait_for(release_gates_then_shutdown(), timeout=5.0)

    assert completed == [0, 1, 2], f"Not all coroutines completed before shutdown; got: {completed}"
    assert service._db is None, "Database connection should be closed after shutdown"


async def test_read_db_property_works_after_init(initialized_service: DatabaseService) -> None:
    """read_db property returns the read-only connection after initialization."""
    conn = initialized_service.read_db
    assert conn is not None

    cursor = await conn.execute("SELECT 1")
    row = await cursor.fetchone()
    assert row[0] == 1


async def test_read_db_property_raises_before_init(service: DatabaseService) -> None:
    """read_db property raises RuntimeError before on_initialize()."""
    with pytest.raises(RuntimeError, match="Read database connection is not initialized"):
        _ = service.read_db


async def test_enqueue_raises_before_init(service: DatabaseService) -> None:
    """enqueue() raises RuntimeError when called before on_initialize()."""

    async def noop() -> None:
        pass

    with pytest.raises(RuntimeError, match="called before on_initialize"):
        service.enqueue(noop())


async def test_enqueue_drops_task_on_queue_full(initialized_service: DatabaseService) -> None:
    """enqueue() drops the coroutine and logs an error when the queue is full."""

    # Block the worker so nothing drains by using a gate coroutine
    gate = asyncio.Event()
    drained: list[int] = []

    async def gated_coro(index: int) -> None:
        await gate.wait()
        drained.append(index)

    # Fill the queue to capacity
    queue = initialized_service._db_write_queue
    max_size = queue.maxsize

    # Put items directly so we don't trigger the put_nowait path yet
    for i in range(max_size):
        await queue.put((gated_coro(i), None))

    # Now queue is full — enqueue() should log an error and return without raising
    dropped_coro_executed = False

    async def should_be_dropped() -> None:
        nonlocal dropped_coro_executed
        dropped_coro_executed = True

    # This must not raise; the coro should be closed (not executed)
    initialized_service.enqueue(should_be_dropped())

    # Release the gate so the worker can drain
    gate.set()
    await queue.join()

    # The dropped coroutine must never have executed
    assert not dropped_coro_executed


async def test_enqueue_logs_backlog_warning_at_100_multiple(initialized_service: DatabaseService) -> None:
    """enqueue() logs a warning when queue depth is a nonzero multiple of 100."""

    gate = asyncio.Event()

    async def gated_coro() -> None:
        await gate.wait()

    queue = initialized_service._db_write_queue

    # Fill 99 slots directly (bypassing enqueue's logging) so the next enqueue hits depth 100
    for _ in range(99):
        await queue.put((gated_coro(), None))

    # The 100th item via enqueue() should trigger the depth warning
    with patch.object(initialized_service, "logger") as mock_logger:
        initialized_service.enqueue(gated_coro())
        # Check that logger.warning was called with "backlog" somewhere in the message
        warning_calls = [str(call) for call in mock_logger.warning.call_args_list]
        assert any("backlog" in c or "depth" in c for c in warning_calls), (
            f"Expected backlog warning, got: {warning_calls}"
        )

    gate.set()
    await queue.join()


async def test_size_failsafe_skips_when_limit_is_zero(initialized_service: DatabaseService) -> None:
    """_check_size_failsafe() returns immediately when db_max_size_mb == 0."""
    initialized_service.hassette.config.database.max_size_mb = 0

    # Patch _get_db_size_mb to detect if it is ever called
    with patch.object(initialized_service, "_get_db_size_mb") as mock_size:
        await initialized_service._check_size_failsafe()
        mock_size.assert_not_called()


async def test_size_failsafe_logs_warning_on_consecutive_triggers(initialized_service: DatabaseService) -> None:
    """_check_size_failsafe() logs a WARNING on the second and subsequent triggers."""
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    # Insert a listener for FK reference
    await db.execute(
        "INSERT INTO listeners (app_key, instance_index, handler_method, topic, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "on_event", "state_changed", TEST_SOURCE_LOCATION),
    )
    await db.commit()

    # Insert some records so there is something to delete
    now = time.time()
    for i in range(10):
        ts = now - (100 - i)
        await db.execute(
            "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
            "VALUES (1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    initialized_service.hassette.config.database.max_size_mb = 0.0001  # guaranteed to trigger

    # First trigger — counter goes to 1, no warning logged
    with patch.object(initialized_service, "logger") as mock_logger:
        await initialized_service._check_size_failsafe()
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert not any("consecutive" in c for c in warning_calls)

    assert initialized_service._consecutive_size_triggers == 1

    # Re-insert records for second trigger
    for i in range(10):
        ts = now - (50 - i)
        await db.execute(
            "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
            "VALUES (1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    # Second trigger — counter goes to 2, warning IS logged
    with patch.object(initialized_service, "logger") as mock_logger:
        await initialized_service._check_size_failsafe()
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any("consecutive" in c for c in warning_calls), (
            f"Expected consecutive-trigger warning on second call, got: {warning_calls}"
        )
