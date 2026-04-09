"""Integration tests for SessionManager."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.session_manager import SessionManager
from hassette.events import HassetteServiceEvent
from hassette.events.base import HassettePayload
from hassette.events.hassette import ServiceStatusPayload
from hassette.types import ResourceRole, ResourceStatus, Topic


def _make_crashed_event(
    resource_name: str = "TestService",
    exception_type: str = "RuntimeError",
    exception: str = "something broke",
    exception_traceback: str = "Traceback ...",
) -> HassetteServiceEvent:
    """Build a CRASHED HassetteServiceEvent for testing."""
    return HassetteServiceEvent(
        topic=Topic.HASSETTE_EVENT_SERVICE_STATUS,
        payload=HassettePayload(
            event_type=str(ResourceStatus.CRASHED),
            data=ServiceStatusPayload(
                resource_name=resource_name,
                role=ResourceRole.SERVICE,
                status=ResourceStatus.CRASHED,
                previous_status=ResourceStatus.FAILED,
                exception=exception,
                exception_type=exception_type,
                exception_traceback=exception_traceback,
            ),
        ),
    )


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    """Create a mock Hassette with database config pointing to tmp_path."""
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def db_service(mock_hassette: MagicMock) -> AsyncIterator[DatabaseService]:
    """Provide an initialized DatabaseService for session tests."""
    service = DatabaseService(mock_hassette, parent=mock_hassette)
    await service.on_initialize()
    try:
        yield service
    finally:
        await service.on_shutdown()


@pytest.fixture
def session_manager(mock_hassette: MagicMock, db_service: DatabaseService) -> SessionManager:
    """Create a SessionManager wired to the test DatabaseService."""
    return SessionManager(mock_hassette, database_service=db_service, parent=mock_hassette)


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

    event = _make_crashed_event(
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

    event = _make_crashed_event()
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
    event = _make_crashed_event()
    await session_manager.on_service_crashed(event)

    cursor = await db_service.db.execute("SELECT count(*) FROM sessions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_on_service_crashed_db_not_initialized(mock_hassette: MagicMock) -> None:
    """on_service_crashed returns early when database is not initialized."""
    db_service_mock = MagicMock()
    type(db_service_mock).db = property(lambda _: (_ for _ in ()).throw(RuntimeError("not initialized")))

    sm = SessionManager(mock_hassette, database_service=db_service_mock, parent=mock_hassette)
    sm._session_id = 1  # pretend a session was created

    event = _make_crashed_event()
    # Should not raise — logs warning and returns
    await sm.on_service_crashed(event)


async def test_finalize_session_no_session(session_manager: SessionManager) -> None:
    """finalize_session returns early when no session has been created."""
    # Should not raise — early return
    await session_manager.finalize_session()


async def test_finalize_session_db_not_initialized(mock_hassette: MagicMock) -> None:
    """finalize_session returns early when database is not initialized."""
    db_service_mock = MagicMock()
    type(db_service_mock).db = property(lambda _: (_ for _ in ()).throw(RuntimeError("not initialized")))

    sm = SessionManager(mock_hassette, database_service=db_service_mock, parent=mock_hassette)
    sm._session_id = 1  # pretend a session was created

    # Should not raise — logs warning and returns
    await sm.finalize_session()


async def test_on_service_crashed_db_error(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """on_service_crashed handles sqlite3.Error during the UPDATE."""
    await session_manager.create_session()

    # Patch execute to raise on the crash UPDATE
    db_service.db.execute = AsyncMock(side_effect=sqlite3.OperationalError("disk I/O error"))

    event = _make_crashed_event()
    # submit() awaits the result, but _do_on_service_crashed catches the exception internally
    await session_manager.on_service_crashed(event)


async def test_finalize_session_db_error(session_manager: SessionManager, db_service: DatabaseService) -> None:
    """finalize_session handles sqlite3.Error during the UPDATE."""
    await session_manager.create_session()

    # Patch execute to raise on the finalize UPDATE
    db_service.db.execute = AsyncMock(side_effect=sqlite3.OperationalError("disk I/O error"))

    # Should not raise — _do_finalize_session catches the exception and logs
    await session_manager.finalize_session()
