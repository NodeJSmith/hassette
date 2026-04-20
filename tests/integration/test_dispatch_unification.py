"""Integration tests for WP04 — unified dispatch paths and framework listener registration.

Tests verify:
1. All listeners produce telemetry (HandlerInvocationRecord queued), regardless of db_id state.
2. Pre-registration listeners (db_id=None at fire time) produce orphan records (listener_id=None).
3. Framework listeners register with app_key='__hassette__' and source_tier='framework'.
4. Framework listeners produce execution records with source_tier='framework'.
5. reconcile_registrations() rejects app_key='__hassette__' with a warning and no-op.
6. Full reconciliation for an app does NOT delete framework listener rows.
7. once=True deferred cleanup deletes stale app listeners but not framework ones.
8. All scheduled jobs produce telemetry (JobExecutionRecord queued), regardless of db_id state.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.scheduler.classes import JobExecutionRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config pointing to tmp_path."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.command_executor_log_level = "INFO"
    hassette.config.bus_service_log_level = "INFO"
    hassette.config.scheduler_service_log_level = "INFO"
    hassette.config.scheduler_min_delay_seconds = 0.1
    hassette.config.scheduler_max_delay_seconds = 60.0
    hassette.config.scheduler_default_delay_seconds = 1.0
    hassette.config.bus_excluded_domains = ()
    hassette.config.bus_excluded_entities = ()
    hassette.config.log_all_events = False
    hassette.config.log_all_hass_events = False
    hassette.config.log_all_hassette_events = False
    hassette.config.telemetry_write_queue_max = 1000
    hassette.config.db_write_queue_max = 2000
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def initialized_db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    """Initialize a real DatabaseService and create a session row."""
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    try:
        ts = time.time()
        cursor = await db_service.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (ts, ts),
        )
        session_id = cursor.lastrowid
        assert session_id is not None
        mock_hassette.session_id = session_id
        await db_service.db.commit()
        mock_hassette.database_service = db_service
        yield db_service, session_id
    finally:
        await db_service.on_shutdown()


@pytest.fixture
async def executor(mock_hassette: MagicMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    mock_hassette.wait_for_ready = AsyncMock(return_value=True)
    exc = CommandExecutor(mock_hassette, parent=mock_hassette)
    await exc.on_initialize()
    return exc


def _make_mock_listener(*, listener_id: int = 1, db_id: int | None = None, source_tier: str = "app") -> MagicMock:
    """Return a mock Listener with configurable db_id and source_tier."""
    listener = MagicMock()
    listener.listener_id = listener_id
    listener.db_id = db_id
    listener.source_tier = source_tier
    listener.invoke = AsyncMock()
    return listener


# ---------------------------------------------------------------------------
# Subtask 1 & 2: _dispatch always uses _make_tracked_invoke_fn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_listeners_produce_telemetry(executor: CommandExecutor) -> None:
    """All listeners produce HandlerInvocationRecord when fired, even when db_id is set."""
    listener = _make_mock_listener(db_id=42, source_tier="app")
    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="hass.event.test",
        listener_id=42,
        source_tier="app",
        effective_timeout=None,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.listener_id == 42
    assert record.status == "success"
    assert record.source_tier == "app"


@pytest.mark.asyncio
async def test_pre_registration_listener_produces_orphan_record(executor: CommandExecutor) -> None:
    """Pre-registration listeners (db_id=None at fire time) produce records with listener_id=None."""
    listener = _make_mock_listener(db_id=None, source_tier="app")
    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="hass.event.test",
        listener_id=None,
        source_tier="app",
        effective_timeout=None,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.listener_id is None
    assert record.status == "success"


# ---------------------------------------------------------------------------
# Subtask 4 & 5: register_framework_listener() and _register_then_add_route
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_framework_listener_registration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    mock_hassette: MagicMock,
) -> None:
    """register_framework_listener() writes a DB row with app_key='__hassette__' and source_tier='framework'."""
    db_service, _ = initialized_db
    stream = MagicMock()
    bus_service = BusService(mock_hassette, stream=stream, executor=executor, parent=mock_hassette)

    async def dummy_handler(event: object) -> None:
        pass

    # Directly invoke _register_then_add_route with a pre-built framework listener
    from hassette.bus.listeners import Listener

    listener = Listener.create(
        task_bucket=MagicMock(),
        owner_id="__hassette__:test.framework_listener",
        topic="hassette.event.service_status",
        handler=dummy_handler,
        app_key="__hassette__",
        instance_index=0,
        name="hassette.test.framework_listener",
        source_tier="framework",
    )
    # Patch router.add_route to be a no-op so we only test DB registration
    bus_service.router = MagicMock()
    bus_service.router.add_route = AsyncMock()

    await bus_service._register_then_add_route(listener)

    # Verify the DB row
    cursor = await db_service.db.execute(
        "SELECT app_key, source_tier, name FROM listeners WHERE name = ?",
        ("hassette.test.framework_listener",),
    )
    row = await cursor.fetchone()
    assert row is not None, "Framework listener was not persisted to DB"
    assert row[0] == "__hassette__", f"Expected app_key='__hassette__', got {row[0]!r}"
    assert row[1] == "framework", f"Expected source_tier='framework', got {row[1]!r}"
    assert row[2] == "hassette.test.framework_listener"


@pytest.mark.asyncio
async def test_framework_listener_produces_telemetry(executor: CommandExecutor) -> None:
    """Framework listeners produce execution records with source_tier='framework'."""
    listener = _make_mock_listener(db_id=99, source_tier="framework")
    cmd = InvokeHandler(
        listener=listener,
        event=MagicMock(),
        topic="hassette.event.service_status",
        listener_id=99,
        source_tier="framework",
        effective_timeout=None,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, HandlerInvocationRecord)
    assert record.listener_id == 99
    assert record.source_tier == "framework"
    assert record.status == "success"


# ---------------------------------------------------------------------------
# Subtask 9: reconcile_registrations guard for __hassette__
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_guard_rejects_hassette(
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """reconcile_registrations('__hassette__', ...) returns without deleting anything."""
    db_service, _ = initialized_db
    repository = TelemetryRepository(db_service)

    # Insert a framework listener row
    cursor = await db_service.db.execute(
        """
        INSERT INTO listeners (
            app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            source_location, source_tier, name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "__hassette__",
            0,
            "hassette.core.on_crash",
            "hassette.event.service_status",
            None,
            None,
            0,
            0,
            "core.py:1",
            "framework",
            "hassette.session_manager.on_service_crashed",
        ),
    )
    row = await cursor.fetchone()
    assert row is not None
    framework_listener_id = row[0]
    await db_service.db.commit()

    # Run reconciliation for __hassette__ — should be a no-op
    await repository.reconcile_registrations("__hassette__", [], [], session_id=None)

    # Verify the row still exists
    cursor = await db_service.db.execute(
        "SELECT id FROM listeners WHERE id = ?",
        (framework_listener_id,),
    )
    surviving_row = await cursor.fetchone()
    assert surviving_row is not None, "Framework listener was deleted by reconcile_registrations — guard failed"


@pytest.mark.asyncio
async def test_reconciliation_preserves_framework_actors(
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """Full reconciliation for an app key does NOT touch framework listener rows."""
    db_service, _ = initialized_db
    repository = TelemetryRepository(db_service)

    # Insert a framework listener row
    cursor = await db_service.db.execute(
        """
        INSERT INTO listeners (
            app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            source_location, source_tier, name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "__hassette__",
            0,
            "service_watcher.restart_service",
            "hassette.event.service_status",
            None,
            None,
            0,
            0,
            "service_watcher.py:1",
            "framework",
            "hassette.service_watcher.restart_service",
        ),
    )
    fw_row = await cursor.fetchone()
    assert fw_row is not None
    framework_id = fw_row[0]

    # Insert an app listener row that is NOT in live_ids → should be deleted
    cursor = await db_service.db.execute(
        """
        INSERT INTO listeners (
            app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority,
            source_location, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        ("my_app", 0, "my_app.stale_handler", "hass.event.state_changed", None, None, 0, 0, "app.py:1", "app"),
    )
    app_row = await cursor.fetchone()
    assert app_row is not None
    stale_app_id = app_row[0]
    await db_service.db.commit()

    # Reconcile the app (not framework) with empty live IDs
    await repository.reconcile_registrations("my_app", [], [], session_id=None)

    # Framework row must survive
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (framework_id,))
    assert (await cursor.fetchone()) is not None, "Framework listener was deleted during app reconciliation"

    # Stale app row must be deleted (no history)
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (stale_app_id,))
    assert (await cursor.fetchone()) is None, "Stale app listener was NOT deleted during reconciliation"


# ---------------------------------------------------------------------------
# Subtask 10: once=True deferred cleanup in SessionManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_once_true_deferred_cleanup(
    initialized_db: tuple[DatabaseService, int],
) -> None:
    """_do_cleanup_once_listeners deletes stale app once=True listeners from stopped sessions."""
    db_service, current_session_id = initialized_db
    ts = time.time()

    # Create a stopped (previous) session
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, stopped_at, status) VALUES (?, ?, ?, 'success')",
        (ts - 100, ts - 50, ts - 50),
    )
    prev_session_id = cursor.lastrowid
    assert prev_session_id is not None

    # Insert a once=True app listener
    cursor = await db_service.db.execute(
        """
        INSERT INTO listeners (
            app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority, source_location, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        ("my_app", 0, "my_app.on_once", "hass.event.state_changed", None, None, 1, 0, "app.py:1", "app"),
    )
    once_row = await cursor.fetchone()
    assert once_row is not None
    once_listener_id = once_row[0]

    # Insert an invocation record for this listener in the PREVIOUS session
    await db_service.db.execute(
        """
        INSERT INTO handler_invocations (
            listener_id, session_id, execution_start_ts, duration_ms, status, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (once_listener_id, prev_session_id, ts - 60, 1.0, "success", "app"),
    )

    # Insert a framework once=True listener (must NOT be deleted)
    cursor = await db_service.db.execute(
        """
        INSERT INTO listeners (
            app_key, instance_index, handler_method, topic,
            debounce, throttle, once, priority, source_location, source_tier, name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "__hassette__",
            0,
            "hassette.core.once_listener",
            "hassette.event.service_status",
            None,
            None,
            1,
            0,
            "core.py:1",
            "framework",
            "hassette.core.once_listener",
        ),
    )
    fw_once_row = await cursor.fetchone()
    assert fw_once_row is not None
    fw_once_listener_id = fw_once_row[0]

    # Also add an invocation for the framework listener in previous session
    await db_service.db.execute(
        """
        INSERT INTO handler_invocations (
            listener_id, session_id, execution_start_ts, duration_ms, status, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (fw_once_listener_id, prev_session_id, ts - 60, 1.0, "success", "framework"),
    )
    await db_service.db.commit()

    # Run the cleanup SQL directly (same as SessionManager._do_cleanup_once_listeners)
    await db_service.db.execute(
        """
        DELETE FROM listeners
        WHERE once = 1
          AND source_tier = 'app'
          AND NOT EXISTS (
              SELECT 1 FROM handler_invocations
              WHERE listener_id = listeners.id AND session_id = ?
          )
          AND EXISTS (
              SELECT 1 FROM sessions
              WHERE id = (
                  SELECT session_id FROM handler_invocations
                  WHERE listener_id = listeners.id
                  LIMIT 1
              )
              AND stopped_at IS NOT NULL
          )
        """,
        (current_session_id,),
    )
    await db_service.db.commit()

    # App once=True listener from stopped session should be deleted
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (once_listener_id,))
    assert (await cursor.fetchone()) is None, "Stale app once=True listener was NOT deleted"

    # Framework once=True listener must survive
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (fw_once_listener_id,))
    assert (await cursor.fetchone()) is not None, "Framework once=True listener was incorrectly deleted"


# ---------------------------------------------------------------------------
# Subtask 7: All scheduler jobs produce telemetry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_jobs_produce_telemetry(executor: CommandExecutor) -> None:
    """All scheduled jobs produce JobExecutionRecord when fired, even with db_id set."""
    job = MagicMock()
    job.source_tier = "app"

    async def _callable() -> None:
        pass

    cmd = ExecuteJob(
        job=job,
        callable=_callable,
        job_db_id=55,
        source_tier="app",
        effective_timeout=None,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.job_id == 55
    assert record.status == "success"
    assert record.source_tier == "app"


@pytest.mark.asyncio
async def test_pre_registration_job_produces_orphan_record(executor: CommandExecutor) -> None:
    """Jobs with db_id=None at fire time produce records with job_id=None."""
    job = MagicMock()
    job.source_tier = "app"

    async def _callable() -> None:
        pass

    cmd = ExecuteJob(
        job=job,
        callable=_callable,
        job_db_id=None,
        source_tier="app",
        effective_timeout=None,
    )

    await executor.execute(cmd)

    assert not executor._write_queue.empty()
    record = executor._write_queue.get_nowait()
    assert isinstance(record, JobExecutionRecord)
    assert record.job_id is None
    assert record.status == "success"
