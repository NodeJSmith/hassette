"""Integration tests for SessionManager."""

import sqlite3
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.session_manager import SessionManager
from hassette.test_utils.helpers import make_crashed_event


@pytest.fixture
async def db_service(db_hassette: MagicMock) -> AsyncIterator[DatabaseService]:
    """Provide an initialized DatabaseService for session tests."""
    service = DatabaseService(db_hassette, parent=None)
    await service.on_initialize()
    try:
        yield service
    finally:
        await service.on_shutdown()


@pytest.fixture
def session_manager(db_hassette: MagicMock, db_service: DatabaseService) -> SessionManager:
    """Create a SessionManager wired to the test DatabaseService."""
    return SessionManager(db_hassette, database_service=db_service, parent=None)


async def test_session_manager_creates_session(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """create_session inserts a 'running' session row and sets session_id."""
    await session_manager.create_session()

    session_id = session_manager.session_id
    assert isinstance(session_id, int)
    assert session_id > 0

    cursor = await db_service.db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "running"
    assert row[1] is None  # stopped_at is NULL while running


async def test_session_manager_marks_orphaned_sessions(
    session_manager: SessionManager, db_service: DatabaseService
) -> None:
    """mark_orphaned_sessions marks stuck 'running' sessions as 'unknown'."""
    db = db_service.db

    # Insert a fake 'running' session to simulate an orphan
    heartbeat_ts = time.time() - 600
    await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (heartbeat_ts - 100, heartbeat_ts),
    )
    await db.commit()

    cursor = await db.execute("SELECT id FROM sessions WHERE status = 'running'")
    row = await cursor.fetchone()
    assert row is not None
    orphan_id = row[0]

    await session_manager.mark_orphaned_sessions()

    cursor = await db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (orphan_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "unknown"
    assert row[1] == pytest.approx(heartbeat_ts, abs=1)


async def test_session_manager_records_crash(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """on_service_crashed writes failure details to the session row."""
    await session_manager.create_session()
    session_id = session_manager.session_id

    event = make_crashed_event(
        resource_name="WebSocketService",
        exception_type="ConnectionError",
        exception="lost connection",
        exception_traceback="Traceback (most recent call last):\n  ...",
    )

    await session_manager.on_service_crashed(event)

    cursor = await db_service.db.execute(
        "SELECT status, error_type, error_message, error_traceback FROM sessions WHERE id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "failure"
    assert row[1] == "ConnectionError"
    assert row[2] == "lost connection"
    assert row[3] == "Traceback (most recent call last):\n  ..."


async def test_session_manager_finalizes_session(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """finalize_session writes 'success' status and stopped_at when no crash occurred."""
    await session_manager.create_session()
    session_id = session_manager.session_id
    db_path = db_service._db_path

    await session_manager.finalize_session()

    # Read via direct connection since the async one may still be open
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row is not None
        assert row[0] == "success"
        assert row[1] is not None
    finally:
        conn.close()


async def test_session_id_raises_before_create(session_manager: SessionManager) -> None:
    """session_id raises RuntimeError if accessed before create_session()."""
    with pytest.raises(RuntimeError, match="Session ID is not initialized"):
        _ = session_manager.session_id


async def test_finalize_session_preserves_failure(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """finalize_session does not overwrite 'failure' status set by on_service_crashed."""
    await session_manager.create_session()
    session_id = session_manager.session_id

    event = make_crashed_event()
    await session_manager.on_service_crashed(event)

    db_path = db_service._db_path
    await session_manager.finalize_session()

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row is not None
        assert row[0] == "failure"  # NOT overwritten to "success"
        assert row[1] is not None  # stopped_at IS set
    finally:
        conn.close()


async def test_mark_orphaned_sessions_no_orphans(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """mark_orphaned_sessions is a no-op when no sessions are in 'running' status."""
    await session_manager.mark_orphaned_sessions()

    cursor = await db_service.db.execute("SELECT count(*) FROM sessions WHERE status = 'unknown'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_on_service_crashed_no_session(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """on_service_crashed returns early when no session has been created."""
    event = make_crashed_event()
    await session_manager.on_service_crashed(event)

    cursor = await db_service.db.execute("SELECT count(*) FROM sessions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_on_service_crashed_db_not_initialized(db_hassette: MagicMock) -> None:
    """on_service_crashed returns early when database is not initialized."""
    db_service_mock = MagicMock()
    db_service_mock.is_db_ready = False

    sm = SessionManager(db_hassette, database_service=db_service_mock, parent=None)
    sm._session_id = 1  # pretend a session was created

    event = make_crashed_event()
    # Should not raise — logs warning and returns
    await sm.on_service_crashed(event)


async def test_finalize_session_no_session(session_manager: SessionManager) -> None:
    """finalize_session returns early when no session has been created."""
    # Should not raise — early return
    await session_manager.finalize_session()


async def test_finalize_session_db_not_initialized(db_hassette: MagicMock) -> None:
    """finalize_session returns early when database is not initialized."""
    db_service_mock = MagicMock()
    db_service_mock.is_db_ready = False

    sm = SessionManager(db_hassette, database_service=db_service_mock, parent=None)
    sm._session_id = 1  # pretend a session was created

    # Should not raise — logs warning and returns
    await sm.finalize_session()


async def test_on_service_crashed_db_error(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """on_service_crashed handles sqlite3.Error during the UPDATE."""
    await session_manager.create_session()

    # Patch execute to raise on the crash UPDATE
    db_service.db.execute = AsyncMock(side_effect=sqlite3.OperationalError("disk I/O error"))

    event = make_crashed_event()
    # submit() awaits the result, but _do_on_service_crashed catches the exception internally
    await session_manager.on_service_crashed(event)


async def test_finalize_session_db_error(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """finalize_session handles sqlite3.Error during the UPDATE."""
    await session_manager.create_session()

    # Patch execute to raise on the finalize UPDATE
    db_service.db.execute = AsyncMock(side_effect=sqlite3.OperationalError("disk I/O error"))

    # Should not raise — _do_finalize_session catches the exception and logs
    await session_manager.finalize_session()


async def test_cleanup_once_listeners_removes_stale_once_listener(
    session_manager: SessionManager, db_service: DatabaseService
) -> None:
    """cleanup_stale_once_listeners deletes once=True listeners from stopped sessions.

    Regression test for the bug where _do_cleanup_once_listeners queried the deleted
    handler_invocations table instead of executions. The error was swallowed by the
    try/except, so once=True listeners silently accumulated across sessions.

    Setup:
    - A stopped session (stopped_at IS NOT NULL) with a once=True listener.
    - An executions row (kind='handler', listener_id set) linking that listener to the stopped session.
    - A current (running) session with NO execution for that listener.

    Expected: cleanup_stale_once_listeners() deletes the once=True listener row.
    """
    db = db_service.db
    now = time.time()

    # Insert a stopped session (stopped_at IS NOT NULL)
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status, stopped_at) VALUES (?, ?, 'success', ?)",
        (now - 600, now - 300, now - 300),
    )
    await db.commit()
    stopped_session_id = cursor.lastrowid
    assert stopped_session_id is not None

    # Insert a once=True listener owned by the stopped session context (session_id tracked via executions)
    cursor = await db.execute(
        """
        INSERT INTO listeners
            (app_key, instance_index, name, handler_method, topic, once, source_location, source_tier)
        VALUES ('test_app', 0, 'test_once_listener', 'on_event', 'test/topic', 1, 'test.py:1', 'app')
        """,
    )
    await db.commit()
    listener_id = cursor.lastrowid
    assert listener_id is not None

    # Insert an executions row for that listener in the stopped session
    cursor = await db.execute(
        """
        INSERT INTO executions
            (kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier)
        VALUES ('handler', ?, ?, ?, 5.0, 'success', 'app')
        """,
        (listener_id, stopped_session_id, now - 400),
    )
    await db.commit()

    # Create the current running session (no execution for this listener)
    await session_manager.create_session()
    current_session_id = session_manager.session_id

    # Confirm the listener exists before cleanup
    cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None, "Listener must exist before cleanup"

    # Run cleanup
    await session_manager.cleanup_stale_once_listeners()

    # The once=True listener from the stopped session should be deleted
    cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is None, (
        f"once=True listener (id={listener_id}) from stopped session {stopped_session_id} "
        f"should be deleted; current_session_id={current_session_id}"
    )
