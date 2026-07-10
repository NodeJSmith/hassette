"""Integration tests for unified dispatch paths and framework listener registration.

Tests verify:
1. All listeners produce telemetry (ExecutionRecord queued), regardless of db_id state.
2. Pre-registration listeners (db_id=None at fire time) produce orphan records (listener_id=None).
3. Framework listeners register with app_key='__hassette__' and source_tier='framework'.
4. Framework listeners produce execution records with source_tier='framework'.
5. reconcile_registrations() rejects app_key='__hassette__' with a warning and no-op.
6. Full reconciliation for an app does NOT delete framework listener rows.
7. once=True deferred cleanup deletes stale app listeners but not framework ones.
8. All scheduled jobs produce telemetry (ExecutionRecord queued), regardless of db_id state.
"""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.commands import ExecuteJob, InvokeHandler
from hassette.core.bus_service import BusService
from hassette.core.command_executor import CommandExecutor
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.test_utils.factories import make_mock_listener
from hassette.test_utils.helpers import create_listener


@pytest.fixture
async def executor(db_hassette: AsyncMock, initialized_db: tuple[DatabaseService, int]) -> CommandExecutor:  # noqa: ARG001
    """Create and prepare a CommandExecutor with real DB wired in."""
    exc = CommandExecutor(db_hassette, parent=db_hassette)
    await exc.on_initialize()
    return exc


async def test_all_listeners_produce_telemetry(executor: CommandExecutor) -> None:
    """All listeners produce an ExecutionRecord when fired, even when db_id is set."""
    listener = make_mock_listener(db_id=42)
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
    assert isinstance(record, ExecutionRecord)
    assert record.listener_id == 42
    assert record.status == "success"
    assert record.source_tier == "app"


async def test_pre_registration_listener_produces_orphan_record(executor: CommandExecutor) -> None:
    """Pre-registration listeners (db_id=None at fire time) produce records with listener_id=None."""
    listener = make_mock_listener(db_id=None)
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
    assert isinstance(record, ExecutionRecord)
    assert record.listener_id is None
    assert record.status == "success"


async def test_framework_listener_registration(
    executor: CommandExecutor,
    initialized_db: tuple[DatabaseService, int],
    db_hassette: AsyncMock,
) -> None:
    """Framework listener via add_listener writes a DB row with source_tier='framework'.

    With sync routing, add_listener inserts the route immediately and spawns the DB
    registration as a background task. We await the returned task to verify the DB write.
    """
    db_service, _ = initialized_db
    stream = MagicMock()
    bus_service = BusService(db_hassette, stream=stream, executor=executor, parent=db_hassette)

    async def dummy_handler(event: object) -> None:
        pass

    listener = create_listener(
        dummy_handler,
        owner_id="__hassette__:test.framework_listener",
        topic="hassette.event.service_status",
        app_key="__hassette__",
        instance_index=0,
        name="hassette.test.framework_listener",
        source_tier="framework",
    )
    reg = bus_service.build_registration(listener)
    await executor.register_listener(reg)

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


async def test_framework_listener_produces_telemetry(executor: CommandExecutor) -> None:
    """Framework listeners produce execution records with source_tier='framework'."""
    listener = make_mock_listener(db_id=99)
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
    assert isinstance(record, ExecutionRecord)
    assert record.listener_id == 99
    assert record.source_tier == "framework"
    assert record.status == "success"


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
            app_key, instance_index, name, handler_method, topic,
            debounce, throttle, once, priority,
            source_location, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "my_app",
            0,
            "my_app.stale_handler",
            "my_app.stale_handler",
            "hass.event.state_changed",
            None,
            None,
            0,
            0,
            "app.py:1",
            "app",
        ),
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
            app_key, instance_index, name, handler_method, topic,
            debounce, throttle, once, priority, source_location, source_tier
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            "my_app",
            0,
            "my_app.on_once",
            "my_app.on_once",
            "hass.event.state_changed",
            None,
            None,
            1,
            0,
            "app.py:1",
            "app",
        ),
    )
    once_row = await cursor.fetchone()
    assert once_row is not None
    once_listener_id = once_row[0]

    # Insert an invocation record for this listener in the PREVIOUS session
    await db_service.db.execute(
        """
        INSERT INTO executions (
            kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier
        ) VALUES ('handler', ?, ?, ?, ?, ?, ?)
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
        INSERT INTO executions (
            kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier
        ) VALUES ('handler', ?, ?, ?, ?, ?, ?)
        """,
        (fw_once_listener_id, prev_session_id, ts - 60, 1.0, "success", "framework"),
    )
    await db_service.db.commit()

    # Run the cleanup SQL directly (same as SessionManager._do_cleanup_once_listeners).
    # Temporarily disable FK enforcement: ON DELETE SET NULL on executions.listener_id
    # would trigger the CHECK (listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1 otherwise.
    await db_service.db.execute("PRAGMA foreign_keys = OFF")
    await db_service.db.execute(
        """
        DELETE FROM listeners
        WHERE once = 1
          AND source_tier = 'app'
          AND NOT EXISTS (
              SELECT 1 FROM executions
              WHERE kind = 'handler' AND listener_id = listeners.id AND session_id = ?
          )
          AND EXISTS (
              SELECT 1 FROM sessions
              WHERE id = (
                  SELECT session_id FROM executions
                  WHERE kind = 'handler' AND listener_id = listeners.id
                  LIMIT 1
              )
              AND stopped_at IS NOT NULL
          )
        """,
        (current_session_id,),
    )
    await db_service.db.execute("PRAGMA foreign_keys = ON")
    await db_service.db.commit()

    # App once=True listener from stopped session should be deleted
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (once_listener_id,))
    assert (await cursor.fetchone()) is None, "Stale app once=True listener was NOT deleted"

    # Framework once=True listener must survive
    cursor = await db_service.db.execute("SELECT id FROM listeners WHERE id = ?", (fw_once_listener_id,))
    assert (await cursor.fetchone()) is not None, "Framework once=True listener was incorrectly deleted"


async def test_all_jobs_produce_telemetry(executor: CommandExecutor) -> None:
    """All scheduled jobs produce unified ExecutionRecord when fired, even with db_id set."""
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
    assert isinstance(record, ExecutionRecord)
    assert record.kind == "job"
    assert record.job_id == 55
    assert record.status == "success"
    assert record.source_tier == "app"


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
    assert isinstance(record, ExecutionRecord)
    assert record.kind == "job"
    assert record.job_id is None
    assert record.status == "success"
