"""Integration tests for DatabaseService with real SQLite."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from hassette.const.misc import SECONDS_PER_DAY
from hassette.core import database_service as database_service_module
from hassette.core.database_service import DatabaseService
from hassette.resources.lifecycle import compute_shutdown_budget
from hassette.utils.aiosqlite_utils import connect_daemon
from tests.support.helpers import (
    DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS,
    DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX,
    async_noop,
    seed_listener_for_fk,
)
from tests.support.mock_hassette import make_mock_hassette

SIZE_FAILSAFE_TRIGGER_MB = 0.0001
"""Tiny max_size_mb guaranteed to trigger the size failsafe on any non-empty DB."""


@pytest.fixture
def mock_hassette_fresh(tmp_path: Path) -> AsyncMock:
    """Create a mock Hassette with a fresh (empty) data_dir for migration-from-scratch tests."""
    return make_mock_hassette(
        sealed=False,
        data_dir=tmp_path,
        set_ready=False,
        database={"telemetry_write_queue_max": DB_HASSETTE_TELEMETRY_WRITE_QUEUE_MAX},
        lifecycle={"resource_shutdown_timeout_seconds": DB_HASSETTE_RESOURCE_SHUTDOWN_TIMEOUT_SECONDS},
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
            "app_manifests",
            "blocking_events",
            "executions",
            "listeners",
            "log_records",
            "scheduled_jobs",
            "sessions",
        ]

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = sorted(row[0] for row in cursor.fetchall())
        # 001.sql defines 13 idx_* indexes (2 listeners, 2 scheduled_jobs, 6 executions, 3 log_records);
        # 004.sql adds 3 more (idx_be_ts, idx_be_app_ts, idx_be_session) → 16 total.
        assert len(indexes) == 16
        assert "idx_listeners_app" in indexes
        assert "idx_listeners_natural" in indexes
        assert "idx_scheduled_jobs_app" in indexes
        assert "idx_scheduled_jobs_natural" in indexes
        assert "idx_exec_listener_time" in indexes
        assert "idx_exec_job_time" in indexes
        assert "idx_exec_status_time" in indexes
        assert "idx_exec_time" in indexes
        assert "idx_exec_session" in indexes
        assert "idx_exec_source_tier_time" in indexes
        assert "idx_lr_time" in indexes
        assert "idx_lr_exec" in indexes
        assert "idx_lr_app_time" in indexes
        assert "idx_be_ts" in indexes
        assert "idx_be_app_ts" in indexes
        assert "idx_be_session" in indexes

        # No uq_* unique indexes in the unified schema (natural-key uniqueness is
        # handled by idx_listeners_natural / idx_scheduled_jobs_natural); execution_id
        # uniqueness is declared inline as UNIQUE on the column, not as a named uq_ index.
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'uq_%'")
        unique_indexes = sorted(row[0] for row in cursor.fetchall())
        assert unique_indexes == []
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
    """update_heartbeat updates last_heartbeat_at."""
    session_id = initialized_service.hassette.session_id
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    initial_heartbeat = row[0]

    await asyncio.sleep(0.05)
    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()

    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_retention_cleanup(initialized_service: DatabaseService) -> None:
    """run_retention_cleanup deletes old records but keeps recent ones."""
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    await seed_listener_for_fk(db)

    # Insert a scheduled_job for FK reference
    await db.execute(
        "INSERT INTO scheduled_jobs "
        "(app_key, instance_index, job_name, handler_method, source_location, schedule_status)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("test.App", 0, "my_job", "run_job", "test.py:2", "scheduled"),
    )
    await db.commit()

    now = time.time()
    old_ts = now - (8 * SECONDS_PER_DAY)  # 8 days ago (beyond 7-day retention)
    # Within both the 7-day retention_days window and the 1-day framework_retention_days window.
    # Rows here default to source_tier='app', so only the app-tier cutoff (retention_days)
    # actually applies to them — the 0.1-day margin keeps this test correct regardless.
    recent_ts = now - (0.1 * SECONDS_PER_DAY)  # ~2.4 hours ago (within both retention windows)

    # Insert old and recent handler executions (kind='handler', listener_id set)
    await db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
        (session_id, old_ts),
    )
    await db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
        (session_id, recent_ts),
    )

    # Insert old and recent job executions (kind='job', job_id set)
    await db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', 1, ?, ?, 5.0, 'success')",
        (session_id, old_ts),
    )
    await db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', 1, ?, ?, 5.0, 'success')",
        (session_id, recent_ts),
    )
    await db.commit()

    await initialized_service.run_retention_cleanup()

    await initialized_service._db_write_queue.join()

    # Old records should be deleted, recent ones retained.
    # Both handler and job records now live in executions; 2 old removed, 2 recent kept.
    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 2


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
    initialized_service.hassette.config.database.heartbeat_interval_seconds = 0.1
    initialized_service.hassette.config.database.retention_interval_seconds = 0.1

    await asyncio.wait_for(initialized_service.serve(), timeout=5.0)

    await shutdown_task

    await initialized_service._db_write_queue.join()

    # Heartbeat should have been updated
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat


async def test_serve_runs_size_failsafe(initialized_service: DatabaseService) -> None:
    """serve() runs the size-failsafe branch during the loop, on its own interval."""

    async def shutdown_after_loop() -> None:
        await asyncio.sleep(0.3)
        initialized_service.shutdown_event.set()

    shutdown_task = asyncio.create_task(shutdown_after_loop())

    # heartbeat_interval_seconds drives the loop's own wait_for cadence, so it must be small
    # too -- otherwise the loop never wakes up to check whether size_failsafe_interval_seconds
    # has elapsed.
    initialized_service.hassette.config.database.heartbeat_interval_seconds = 0.1
    initialized_service.hassette.config.database.size_failsafe_interval_seconds = 0.1

    with patch.object(
        initialized_service, "run_size_failsafe", wraps=initialized_service.run_size_failsafe
    ) as mock_run_size_failsafe:
        await asyncio.wait_for(initialized_service.serve(), timeout=5.0)

    await shutdown_task

    # The size-failsafe branch should have been reached at least once
    mock_run_size_failsafe.assert_called()


async def test_heartbeat_failure_counter_tracks_failures(initialized_service: DatabaseService) -> None:
    """Heartbeat failures increment counter; recovery resets it."""
    assert initialized_service._consecutive_heartbeat_failures == 0

    # Close the DB to force heartbeat failures
    assert initialized_service._db is not None
    await initialized_service._db.close()

    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 2

    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 3

    # Restore a valid connection and verify recovery resets counter
    initialized_service._db = await connect_daemon(initialized_service._db_path)
    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_heartbeat_recovery_resets_counter(initialized_service: DatabaseService) -> None:
    """A successful heartbeat after failures resets the failure counter."""
    # Simulate one failure by temporarily breaking the connection
    real_db = initialized_service._db
    initialized_service._db = MagicMock()
    initialized_service._db.execute = AsyncMock(side_effect=sqlite3.OperationalError("db error"))

    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    # Restore real connection — next heartbeat should succeed and reset
    initialized_service._db = real_db
    await initialized_service.update_heartbeat()

    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_db_property_works_after_init(initialized_service: DatabaseService) -> None:
    """Db property returns the connection after initialization."""
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

    initialized_service.hassette.config.database.heartbeat_interval_seconds = 0.01
    with pytest.raises(RuntimeError, match="Heartbeat failed 3 consecutive times"):
        await asyncio.wait_for(initialized_service.serve(), timeout=5.0)


async def test_serve_raises_when_write_worker_is_wedged(initialized_service: DatabaseService) -> None:
    """A wedged write worker escalates to RuntimeError instead of parking serve() forever.

    The worker never raises — it just stops draining the queue — so only the submit()
    timeout in update_heartbeat() can turn the hang into a counted heartbeat failure.
    """
    gate = asyncio.Event()
    wedged = asyncio.Event()

    async def wedge() -> None:
        wedged.set()
        await gate.wait()

    # Occupy the worker with a coroutine that never completes, so nothing queued behind
    # it is ever executed.
    assert initialized_service.enqueue(wedge()) is True
    await asyncio.wait_for(wedged.wait(), timeout=1)

    initialized_service.hassette.config.database.heartbeat_interval_seconds = 0.01
    try:
        with (
            patch("hassette.core.database_service._HEARTBEAT_WRITE_TIMEOUT_SECONDS", 0.05),
            pytest.raises(RuntimeError, match="Heartbeat failed 3 consecutive times"),
        ):
            await asyncio.wait_for(initialized_service.serve(), timeout=5.0)

        assert initialized_service._consecutive_heartbeat_failures == 3
    finally:
        gate.set()


async def test_shutdown_drain_is_bounded_when_worker_is_dead(service: DatabaseService) -> None:
    """on_shutdown() gives up on queue.join() rather than blocking on a dead worker."""
    await service.on_initialize()

    # Kill the worker with an item still queued — nothing will ever call task_done() for it,
    # so an unbounded queue.join() could never complete.
    assert service._db_worker_task is not None
    service._db_worker_task.cancel()
    await asyncio.gather(service._db_worker_task, return_exceptions=True)
    assert service.enqueue(async_noop()) is True

    with patch("hassette.core.database_service._SHUTDOWN_DRAIN_TIMEOUT_SECONDS", 0.05):
        await asyncio.wait_for(service.on_shutdown(), timeout=5.0)

    assert service._db is None, "Database connection should be closed after a bounded drain"
    assert service._db_write_queue is None


async def test_shutdown_drain_is_bounded_by_the_remaining_hooks_pool(service: DatabaseService) -> None:
    """A hooks pool smaller than _SHUTDOWN_DRAIN_TIMEOUT_SECONDS is what bounds the drain.

    run_hooks() already cancels on_shutdown() at the hooks-pool deadline, so a drain that
    outlasts the pool loses close_connections() entirely. Note this test deliberately does not
    patch _SHUTDOWN_DRAIN_TIMEOUT_SECONDS — the 5s constant must lose to the pool share.
    """
    await service.on_initialize()

    assert service._db_worker_task is not None
    service._db_worker_task.cancel()
    await asyncio.gather(service._db_worker_task, return_exceptions=True)
    assert service.enqueue(async_noop()) is True

    # A tiny total scales every stage down proportionally, leaving a hooks pool far under 5s.
    loop = asyncio.get_running_loop()
    service._shutdown_budget = compute_shutdown_budget(0.2, loop.time())

    started = loop.time()
    await asyncio.wait_for(service.on_shutdown(), timeout=5.0)
    elapsed = loop.time() - started

    assert elapsed < 1.0, f"drain ignored the hooks pool and used the 5s constant instead ({elapsed:.2f}s)"
    assert service._db is None, "Database connection should be closed after a bounded drain"


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
    with pytest.raises(RuntimeError, match="called before on_initialize"):
        service.enqueue(async_noop())


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

    # Patch get_db_size_mb to detect if it is ever called
    with patch.object(initialized_service, "get_db_size_mb") as mock_size:
        await initialized_service._check_size_failsafe()
        mock_size.assert_not_called()


async def test_size_failsafe_logs_warning_on_consecutive_triggers(initialized_service: DatabaseService) -> None:
    """_check_size_failsafe() bumps ``_consecutive_size_triggers`` on every call made while the
    DB stays over the limit — the entry-trigger WARNING it also logs starting on the second
    call is not asserted here (log output is not a behavioral contract; the counter is).
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    await seed_listener_for_fk(db)

    # Insert some executions so there is something for the size failsafe to delete
    now = time.time()
    for i in range(10):
        ts = now - (100 - i)
        await db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
            " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    # First trigger — counter goes to 1.
    await initialized_service._check_size_failsafe()
    assert initialized_service._consecutive_size_triggers == 1

    # Re-insert records for second trigger
    for i in range(10):
        ts = now - (50 - i)
        await db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
            " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    # Second trigger — counter goes to 2.
    await initialized_service._check_size_failsafe()
    assert initialized_service._consecutive_size_triggers == 2


async def test_size_failsafe_logs_warning_on_exhaustion(initialized_service: DatabaseService) -> None:
    """_check_size_failsafe() bumps ``_consecutive_exhaustion_triggers`` when the DB stays over
    the size limit after every retention tier has been drained. The all-tiers-exhausted WARNING
    it also logs on that path is not asserted here (log output is not a behavioral contract; the
    counter is).
    """
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    await seed_listener_for_fk(db)

    now = time.time()
    for i in range(10):
        ts = now - (100 - i)
        await db.execute(
            "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
            " VALUES ('handler', 1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    # Small enough that draining every tier still leaves the real DB over the limit.
    initialized_service.hassette.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    await initialized_service._check_size_failsafe()
    assert initialized_service._consecutive_exhaustion_triggers == 1

    await initialized_service._check_size_failsafe()
    assert initialized_service._consecutive_exhaustion_triggers == 2


async def test_startup_size_failsafe_check_is_bounded_by_timeout(
    fresh_service: DatabaseService, mock_hassette_fresh: MagicMock
) -> None:
    """on_initialize() does not hang past its readiness budget if the startup size failsafe
    check runs long — it degrades gracefully and lets startup proceed, rather than blocking
    on_initialize() (and therefore wait_for_ready()'s startup_timeout_seconds) for as long as
    vacuum/checkpoint work on a large backlog happens to take.
    """
    # config.lifecycle is a real, fixture-owned Pydantic model — replace it with a copy rather
    # than mutating the shared instance in place.
    mock_hassette_fresh.config.lifecycle = mock_hassette_fresh.config.lifecycle.model_copy(
        update={"startup_timeout_seconds": 0.2}
    )
    # Tiny enough that a fresh, just-migrated (empty) DB is already "over" the limit, so
    # _check_size_failsafe() reaches its real DELETE loop instead of returning immediately.
    mock_hassette_fresh.config.database.max_size_mb = SIZE_FAILSAFE_TRIGGER_MB

    delete_reached = asyncio.Event()
    real_connect_daemon = database_service_module.connect_daemon

    async def connect_daemon_with_delayed_delete(*args: Any, **kwargs: Any) -> aiosqlite.Connection:
        """Wrap a real connection so its first DELETE hangs, faking slow I/O at the actual
        boundary (the sqlite driver call) instead of stubbing out DatabaseService's own logic.
        """
        conn = await real_connect_daemon(*args, **kwargs)
        real_execute = conn.execute

        async def delayed_execute(sql: str, parameters: Any = None) -> aiosqlite.Cursor:
            if sql.strip().upper().startswith("DELETE FROM"):
                delete_reached.set()
                await asyncio.sleep(10)
            return await real_execute(sql, parameters)

        conn.execute = delayed_execute
        return conn

    with patch.object(database_service_module, "connect_daemon", connect_daemon_with_delayed_delete):
        # on_initialize() itself must return well within the sleep duration — proves the
        # asyncio.wait_for() deadline actually bounds the call rather than merely being present
        # in the source.
        await asyncio.wait_for(fresh_service.on_initialize(), timeout=5.0)

    # Proves the real size-failsafe path was exercised (and hung on its own DELETE), not
    # skipped because there was nothing over the limit to clean up.
    assert delete_reached.is_set(), "size failsafe never reached its DELETE statement"

    await fresh_service.on_shutdown()


async def test_run_size_failsafe_enqueues_check_size_failsafe(initialized_service: DatabaseService) -> None:
    """run_size_failsafe() drives _check_size_failsafe() via the write queue.

    initialized_service's fixture config sets max_size_mb=0 (size failsafe disabled by
    default), so it's raised here to a real non-zero limit the tiny test DB is well within --
    _check_size_failsafe() resets _consecutive_size_triggers to 0 whenever the database is
    within its size limit. Seeding a nonzero value and observing it reset to 0 proves
    _check_size_failsafe() genuinely ran, without mocking or spying on it.
    """
    initialized_service.hassette.config.database.max_size_mb = 500
    initialized_service._consecutive_size_triggers = 5

    await initialized_service.run_size_failsafe()
    await initialized_service._db_write_queue.join()

    assert initialized_service._consecutive_size_triggers == 0


async def test_run_size_failsafe_returns_early_when_db_is_none(initialized_service: DatabaseService) -> None:
    """run_size_failsafe() is a no-op when _db is None (never initialized)."""
    # Swap _db out (rather than closing it) so the real connection stays intact and gets
    # restored below -- the fixture's on_shutdown() teardown needs the real reference back
    # to close it; losing it here would orphan the aiosqlite connection until GC.
    real_db = initialized_service._db
    initialized_service._db = None
    try:
        assert initialized_service._db_write_queue is not None
        qsize_before = initialized_service._db_write_queue.qsize()

        await initialized_service.run_size_failsafe()

        # Nothing was enqueued -- the _db is None guard fired, proven by real observable queue state.
        assert initialized_service._db_write_queue.qsize() == qsize_before
    finally:
        initialized_service._db = real_db


async def test_run_size_failsafe_returns_early_when_write_queue_is_none(
    initialized_service: DatabaseService,
) -> None:
    """run_size_failsafe() is a no-op when _db_write_queue is None (post-teardown)."""
    initialized_service.detach_write_queue()
    assert initialized_service._db_write_queue is None

    # No mock needed: enqueue() raises queue_unavailable_error() when _db_write_queue is None,
    # so a clean return here is the observable proof the early-return guard fired first.
    await initialized_service.run_size_failsafe()


async def test_force_terminal_closes_real_connections(initialized_service: DatabaseService) -> None:
    """_force_terminal() must stop the real aiosqlite connections synchronously.

    Regression: force-terminal intentionally skips on_shutdown()/cleanup() (see
    Resource._force_terminal()'s docstring) because production assumes force-terminal is nearly
    always followed by process exit. That assumption doesn't hold in a long-lived process --
    notably the test suite -- where a leaked aiosqlite.Connection instead sits open until
    Python's GC eventually reclaims it, firing an unraisable-exception warning attributed to
    whichever test happens to be running at that moment. Same class of leak fixed for App's cache
    in tests/unit/resources/lifecycle/test_force_terminal.py.
    """
    write_conn = initialized_service._db
    read_conn = initialized_service._read_db
    assert write_conn is not None
    assert read_conn is not None

    initialized_service._force_terminal()

    assert initialized_service._db is None
    assert initialized_service._read_db is None
    assert write_conn._running is False, "the write connection's background thread must be signaled to stop"
    assert read_conn._running is False, "the read connection's background thread must be signaled to stop"
