"""Integration tests for session lifecycle (owned by Hassette)."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
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
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.ready_event = asyncio.Event()
    hassette._session_id = None
    hassette._session_error = False
    return hassette


@pytest.fixture
async def db_service(mock_hassette: MagicMock) -> AsyncIterator[DatabaseService]:
    """Provide an initialized DatabaseService for session tests."""
    service = DatabaseService(mock_hassette, parent=mock_hassette)
    await service.on_initialize()
    try:
        yield service
    finally:
        if service._db is not None:
            await service._db.close()
            service._db = None


async def test_create_session(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """_create_session inserts a 'running' session row and stores the ID on Hassette."""
    from hassette.core.core import Hassette

    # Bind the real _create_session method to our mock, using the real db_service
    mock_hassette._database_service = db_service

    # Call the unbound method with mock_hassette as self
    await Hassette._create_session(mock_hassette)

    session_id = mock_hassette._session_id
    assert session_id is not None
    assert isinstance(session_id, int)

    cursor = await db_service.db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "running"
    assert row[1] is None  # stopped_at is NULL while running


async def test_mark_orphaned_sessions(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """_mark_orphaned_sessions marks stuck 'running' sessions as 'unknown'."""
    from hassette.core.core import Hassette

    mock_hassette._database_service = db_service
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

    await Hassette._mark_orphaned_sessions(mock_hassette)

    cursor = await db.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (orphan_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "unknown"
    assert row[1] == pytest.approx(heartbeat_ts, abs=1)


async def test_on_service_crashed_records_failure(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """_on_service_crashed writes failure details to the session row."""
    from hassette.core.core import Hassette

    mock_hassette._database_service = db_service

    # Create a session first
    await Hassette._create_session(mock_hassette)
    session_id = mock_hassette._session_id

    event = _make_crashed_event(
        resource_name="WebSocketService",
        exception_type="ConnectionError",
        exception="lost connection",
        exception_traceback="Traceback (most recent call last):\n  ...",
    )

    await Hassette._on_service_crashed(mock_hassette, event)

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
    assert mock_hassette._session_error is True


async def test_finalize_session_writes_success(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """_finalize_session writes 'success' when no crash was recorded."""
    from hassette.core.core import Hassette

    mock_hassette._database_service = db_service
    mock_hassette._session_error = False

    await Hassette._create_session(mock_hassette)
    session_id = mock_hassette._session_id
    db_path = db_service._db_path

    await Hassette._finalize_session(mock_hassette)

    # Read via direct connection since the async one may still be open
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row is not None
        assert row[0] == "success"
        assert row[1] is not None
    finally:
        conn.close()


async def test_finalize_session_preserves_failure(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """_finalize_session does not overwrite 'failure' status set by _on_service_crashed."""
    from hassette.core.core import Hassette

    mock_hassette._database_service = db_service

    await Hassette._create_session(mock_hassette)
    session_id = mock_hassette._session_id

    event = _make_crashed_event()
    await Hassette._on_service_crashed(mock_hassette, event)

    db_path = db_service._db_path
    await Hassette._finalize_session(mock_hassette)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT status, stopped_at FROM sessions WHERE id = ?", (session_id,)).fetchone()
        assert row is not None
        assert row[0] == "failure"  # NOT overwritten to "success"
        assert row[1] is not None  # stopped_at IS set
    finally:
        conn.close()


async def test_session_id_property_raises_when_uninitialized() -> None:
    """Accessing session_id before creation raises RuntimeError."""
    from hassette.core.core import Hassette

    # Use an object with _session_id = None to test the property
    obj = type("FakeHassette", (), {"_session_id": None})()
    with pytest.raises(RuntimeError, match="Session ID is not initialized"):
        Hassette.session_id.fget(obj)  # type: ignore[union-attr]


async def test_session_id_property_returns_id(mock_hassette: MagicMock, db_service: DatabaseService) -> None:
    """session_id property returns the ID after session creation."""
    from hassette.core.core import Hassette

    mock_hassette._database_service = db_service
    await Hassette._create_session(mock_hassette)

    # Access via property descriptor to verify the property works
    sid = Hassette.session_id.fget(mock_hassette)  # type: ignore[union-attr]
    assert isinstance(sid, int)
    assert sid > 0
