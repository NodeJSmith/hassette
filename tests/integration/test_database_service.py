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
    hassette.config.db_max_size_mb = 500
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    hassette._session_id = None
    return hassette


@pytest.fixture
def service(mock_hassette: MagicMock) -> DatabaseService:
    """Create a DatabaseService instance (not yet initialized)."""
    return DatabaseService(mock_hassette, parent=mock_hassette)


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
        service.hassette._session_id = cursor.lastrowid
        service.hassette.session_id = cursor.lastrowid
        await service.db.commit()
        yield service
    finally:
        await service.on_shutdown()


async def test_fresh_db_creates_all_tables(initialized_service: DatabaseService) -> None:
    """on_initialize creates all 5 tables and 13 indexes on a fresh database."""
    import sqlite3

    db_path = initialized_service._db_path
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        assert tables == ["handler_invocations", "job_executions", "listeners", "scheduled_jobs", "sessions"]

        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
        indexes = sorted(row[0] for row in cursor.fetchall())
        assert len(indexes) == 12
        assert "idx_hi_listener_time" in indexes
        assert "idx_hi_status_time" in indexes
        assert "idx_hi_time" in indexes
        assert "idx_hi_session" in indexes
        assert "idx_je_job_time" in indexes
        assert "idx_je_status_time" in indexes
        assert "idx_je_time" in indexes
        assert "idx_je_session" in indexes
        assert "idx_listeners_app" in indexes
        assert "idx_listeners_natural" in indexes
        assert "idx_scheduled_jobs_app" in indexes
        assert "idx_scheduled_jobs_natural" in indexes
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
    assert initialized_service._db_write_queue is not None
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
        ("test.App", 0, "on_event", "state_changed", "test.py:1"),
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
    assert initialized_service._db_write_queue is not None
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
    assert initialized_service._db_write_queue is not None
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
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    await initialized_service._update_heartbeat()
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 2

    await initialized_service._update_heartbeat()
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 3

    # Restore a valid connection and verify recovery resets counter
    initialized_service._db = await aiosqlite.connect(initialized_service._db_path)
    await initialized_service._update_heartbeat()
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 0


async def test_heartbeat_recovery_resets_counter(initialized_service: DatabaseService) -> None:
    """A successful heartbeat after failures resets the failure counter."""
    # Simulate one failure by temporarily breaking the connection
    real_db = initialized_service._db
    initialized_service._db = MagicMock()
    initialized_service._db.execute = AsyncMock(side_effect=sqlite3.OperationalError("db error"))

    await initialized_service._update_heartbeat()
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()
    assert initialized_service._consecutive_heartbeat_failures == 1

    # Restore real connection — next heartbeat should succeed and reset
    initialized_service._db = real_db
    await initialized_service._update_heartbeat()
    assert initialized_service._db_write_queue is not None
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


# ---------------------------------------------------------------------------
# Migration chain integrity tests
# ---------------------------------------------------------------------------

MIGRATIONS_PATH = Path(__file__).resolve().parent.parent.parent / "src" / "hassette" / "migrations"

# Hardcoded because this project uses raw Alembic operations (op.create_table, op.add_column),
# not autogenerate from ORM models — there is no Base.metadata to compare against.
# Update this dict when adding new migrations.
EXPECTED_TABLES = {
    "sessions": {
        "id",
        "started_at",
        "stopped_at",
        "last_heartbeat_at",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
    },
    "listeners": {
        "id",
        "app_key",
        "instance_index",
        "handler_method",
        "topic",
        "debounce",
        "throttle",
        "once",
        "priority",
        "predicate_description",
        "source_location",
        "registration_source",
        "human_description",
        "name",
        "retired_at",
    },
    "scheduled_jobs": {
        "id",
        "app_key",
        "instance_index",
        "job_name",
        "handler_method",
        "trigger_type",
        "trigger_value",
        "repeat",
        "args_json",
        "kwargs_json",
        "source_location",
        "registration_source",
        "retired_at",
    },
    "handler_invocations": {
        "id",
        "listener_id",
        "session_id",
        "execution_start_ts",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
    },
    "job_executions": {
        "id",
        "job_id",
        "session_id",
        "execution_start_ts",
        "duration_ms",
        "status",
        "error_type",
        "error_message",
        "error_traceback",
    },
}


def _make_alembic_config(db_path: Path):
    """Build a programmatic Alembic Config matching production (DatabaseService._run_migrations)."""
    from alembic.config import Config

    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def test_migration_chain_has_no_gaps(tmp_path: Path) -> None:
    """Walk the revision chain from base to heads and verify no gaps or dangling down_revision refs."""
    from alembic.script import ScriptDirectory

    config = _make_alembic_config(tmp_path / "unused.db")
    script = ScriptDirectory.from_config(config)

    revisions = list(script.walk_revisions())
    assert len(revisions) >= 3, f"Expected at least 3 revisions, got {len(revisions)}"

    # Build a set of all known revision IDs
    revision_ids = {rev.revision for rev in revisions}

    for rev in revisions:
        if rev.down_revision is not None:
            # down_revision can be a string or a tuple (for merge migrations)
            down_revs = rev.down_revision if isinstance(rev.down_revision, tuple) else (rev.down_revision,)
            for dr in down_revs:
                assert dr in revision_ids, (
                    f"Revision {rev.revision} references down_revision {dr!r} "
                    f"which does not exist in the script directory"
                )

    # Verify exactly one head (no branch forks)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 head, got {len(heads)}: {heads}"

    # Verify exactly one base
    bases = script.get_bases()
    assert len(bases) == 1, f"Expected exactly 1 base, got {len(bases)}: {bases}"


def test_fresh_db_migrates_to_head(tmp_path: Path) -> None:
    """Create an empty SQLite DB, run 'upgrade head', and verify all expected tables exist."""
    import sqlite3

    from alembic import command

    db_path = tmp_path / "test.db"
    config = _make_alembic_config(db_path)
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        tables = sorted(row[0] for row in cursor.fetchall())
        assert tables == sorted(EXPECTED_TABLES.keys())
    finally:
        conn.close()


def test_sequential_upgrade_from_each_revision(tmp_path: Path) -> None:
    """For each revision, stamp a fresh DB at that revision, then upgrade to head."""
    import sqlite3

    from alembic import command
    from alembic.script import ScriptDirectory

    config = _make_alembic_config(tmp_path / "script_dir.db")
    script = ScriptDirectory.from_config(config)

    # Collect revisions in base-to-head order (walk_revisions yields head-first)
    revisions = list(script.walk_revisions())
    revisions.reverse()

    for i, rev in enumerate(revisions):
        db_path = tmp_path / f"test_{i}_{rev.revision}.db"
        rev_config = _make_alembic_config(db_path)

        # Run migrations up to this revision to create the schema at that point
        command.upgrade(rev_config, rev.revision)

        # Then upgrade from this revision to head
        command.upgrade(rev_config, "head")

        # Verify the DB is at head and has all tables
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
            )
            tables = sorted(row[0] for row in cursor.fetchall())
            assert tables == sorted(EXPECTED_TABLES.keys()), (
                f"After upgrading from {rev.revision} to head, "
                f"expected tables {sorted(EXPECTED_TABLES.keys())} but got {tables}"
            )
        finally:
            conn.close()


def test_migration_schema_matches_expected_columns(tmp_path: Path) -> None:
    """After running all migrations, compare the resulting columns against the expected schema."""
    import sqlite3

    from alembic import command

    db_path = tmp_path / "test.db"
    config = _make_alembic_config(db_path)
    command.upgrade(config, "head")

    conn = sqlite3.connect(db_path)
    try:
        # Get all user tables
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'alembic%' AND name NOT LIKE 'sqlite_%'"
        )
        actual_tables = {row[0] for row in cursor.fetchall()}

        expected_table_names = set(EXPECTED_TABLES.keys())

        # Check for tables in expected but missing from migrations
        missing_tables = expected_table_names - actual_tables
        assert not missing_tables, f"Tables defined in expected schema but missing from DB: {missing_tables}"

        # Check for tables in migrations but not in expected schema
        extra_tables = actual_tables - expected_table_names
        assert not extra_tables, f"Tables in DB but missing from expected schema: {extra_tables}"

        # Compare columns for each table
        for table_name in sorted(actual_tables):
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            actual_columns = {row[1] for row in cursor.fetchall()}
            expected_columns = EXPECTED_TABLES[table_name]

            missing_columns = expected_columns - actual_columns
            assert not missing_columns, (
                f"Table {table_name!r}: columns in expected schema but missing from DB: {missing_columns}"
            )

            extra_columns = actual_columns - expected_columns
            assert not extra_columns, (
                f"Table {table_name!r}: columns in DB but missing from expected schema: {extra_columns}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Size failsafe tests
# ---------------------------------------------------------------------------


async def test_size_failsafe_deletes_oldest_records(initialized_service: DatabaseService) -> None:
    """Size failsafe deletes oldest records when database exceeds the configured limit."""
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    # Insert a listener and scheduled_job for FK references
    await db.execute(
        "INSERT INTO listeners (app_key, instance_index, handler_method, topic, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "on_event", "state_changed", "test.py:1"),
    )
    await db.execute(
        "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "my_job", "run_job", "test.py:2"),
    )
    await db.commit()

    # Insert records with known timestamps: older ones should be deleted first
    now = time.time()
    for i in range(50):
        ts = now - (100 - i)  # oldest first
        await db.execute(
            "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
            "VALUES (1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
        await db.execute(
            "INSERT INTO job_executions (job_id, session_id, execution_start_ts, duration_ms, status) "
            "VALUES (1, ?, ?, 5.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    # Set a very small max size that the DB likely already exceeds
    initialized_service.hassette.config.db_max_size_mb = 0.0001  # ~100 bytes — guaranteed to trigger

    await initialized_service._check_size_failsafe()

    # After failsafe, some records should have been deleted
    cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
    row = await cursor.fetchone()
    assert row is not None
    hi_remaining = row[0]

    cursor = await db.execute("SELECT COUNT(*) FROM job_executions")
    row = await cursor.fetchone()
    assert row is not None
    je_remaining = row[0]

    # With only 50 records and batch size 1000, all should be deleted in one iteration
    assert hi_remaining == 0
    assert je_remaining == 0

    # Sessions table must NOT be touched
    cursor = await db.execute("SELECT COUNT(*) FROM sessions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] >= 1


async def test_size_failsafe_loop_capped_at_10_iterations(initialized_service: DatabaseService) -> None:
    """Size failsafe loop terminates after 10 iterations even if still over limit."""
    session_id = initialized_service.hassette.session_id
    db = initialized_service.db

    # Insert a listener for FK reference
    await db.execute(
        "INSERT INTO listeners (app_key, instance_index, handler_method, topic, source_location)"
        " VALUES (?, ?, ?, ?, ?)",
        ("test.App", 0, "on_event", "state_changed", "test.py:1"),
    )
    await db.commit()

    # Insert records so there's something to delete
    now = time.time()
    for i in range(100):
        ts = now - (200 - i)
        await db.execute(
            "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status) "
            "VALUES (1, ?, ?, 10.0, 'success')",
            (session_id, ts),
        )
    await db.commit()

    # Use a mock _get_db_size_mb that always reports over-limit so the loop runs all 10 iterations
    call_count = 0
    original_get_size = initialized_service._get_db_size_mb

    def always_over_limit() -> float:
        nonlocal call_count
        call_count += 1
        return original_get_size() + 999.0  # always over limit

    with patch.object(initialized_service, "_get_db_size_mb", side_effect=always_over_limit):
        initialized_service.hassette.config.db_max_size_mb = 1
        await initialized_service._check_size_failsafe()

    # _get_db_size_mb is called once before the loop, then once per iteration (10 iterations)
    assert call_count == 11


async def test_startup_size_check_runs(service: DatabaseService) -> None:
    """_check_size_failsafe() is called during on_initialize()."""
    with patch.object(DatabaseService, "_check_size_failsafe", new_callable=AsyncMock) as mock_check:
        await service.on_initialize()
        try:
            mock_check.assert_awaited_once()
        finally:
            await service.on_shutdown()


async def test_serve_runs_heartbeat_retention_and_size_failsafe(initialized_service: DatabaseService) -> None:
    """serve() runs heartbeat, retention cleanup, and size failsafe during the loop."""
    session_id = initialized_service.hassette.session_id
    # Get initial heartbeat
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    initial_heartbeat = row[0]

    size_failsafe_called = False
    original_run_size_failsafe = initialized_service._run_size_failsafe

    async def tracking_size_failsafe() -> None:
        nonlocal size_failsafe_called
        size_failsafe_called = True
        await original_run_size_failsafe()

    async def shutdown_after_loop() -> None:
        await asyncio.sleep(0.3)
        initialized_service.shutdown_event.set()

    shutdown_task = asyncio.create_task(shutdown_after_loop())

    with (
        patch("hassette.core.database_service._HEARTBEAT_INTERVAL_SECONDS", 0.1),
        patch("hassette.core.database_service._RETENTION_INTERVAL_SECONDS", 0.1),
        patch("hassette.core.database_service._SIZE_FAILSAFE_INTERVAL_SECONDS", 0.1),
        patch.object(initialized_service, "_run_size_failsafe", side_effect=tracking_size_failsafe),
    ):
        await asyncio.wait_for(initialized_service.serve(), timeout=5.0)

    await shutdown_task
    assert initialized_service._db_write_queue is not None
    await initialized_service._db_write_queue.join()

    # Heartbeat should have been updated
    cursor = await initialized_service.db.execute("SELECT last_heartbeat_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] > initial_heartbeat

    # Size failsafe should have been called
    assert size_failsafe_called


# ---------------------------------------------------------------------------
# Migration: auto_vacuum
# ---------------------------------------------------------------------------


def test_auto_vacuum_migration(tmp_path: Path) -> None:
    """Migration 005 converts an existing database to auto_vacuum = INCREMENTAL."""
    import sqlite3

    from alembic import command

    db_path = tmp_path / "test.db"

    # Create a DB with tables at migration 004 (auto_vacuum defaults to 0 = NONE)
    config = _make_alembic_config(db_path)
    command.upgrade(config, "004")

    # Verify auto_vacuum is NOT incremental before migration 005
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("PRAGMA auto_vacuum")
        mode_before = cursor.fetchone()[0]
        assert mode_before != 2, f"Expected auto_vacuum != 2 before migration 005, got {mode_before}"
    finally:
        conn.close()

    # Run migration 005
    command.upgrade(config, "005")

    # Verify auto_vacuum is now INCREMENTAL (2)
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute("PRAGMA auto_vacuum")
        mode_after = cursor.fetchone()[0]
        assert mode_after == 2, f"Expected auto_vacuum = 2 after migration 005, got {mode_after}"
    finally:
        conn.close()
