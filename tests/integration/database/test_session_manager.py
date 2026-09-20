"""Integration tests for SessionManager."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator, Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette import HassetteConfig
from hassette.core.database_service import DatabaseService
from hassette.core.session_manager import SessionManager
from hassette.testing import HassetteHarness, build_harness
from hassette.types import ResourceRole
from tests.support.helpers import make_crashed_event


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


async def test_mark_orphaned_sessions_backfills_crashed_session(
    session_manager: SessionManager, db_service: DatabaseService
) -> None:
    """A session with status='failure' and stopped_at NULL gets stopped_at backfilled but keeps its status.

    Reproduces the bug where a service crash set status='failure' but the process died before
    finalize_session() could set stopped_at. The old orphan-marking query only matched
    status='running', so these rows stayed with stopped_at NULL forever — making their
    once=True listeners permanently ineligible for cleanup.
    """
    db = db_service.db

    # Insert a crashed session: status='failure', stopped_at NULL (simulates crash then kill)
    heartbeat_ts = time.time() - 600
    await db.execute(
        """
        INSERT INTO sessions (started_at, last_heartbeat_at, status, error_type, error_message)
        VALUES (?, ?, 'failure', 'ConnectionError', 'lost connection')
        """,
        (heartbeat_ts - 100, heartbeat_ts),
    )
    await db.commit()

    cursor = await db.execute("SELECT id FROM sessions WHERE status = 'failure'")
    row = await cursor.fetchone()
    assert row is not None
    crashed_session_id = row[0]

    await session_manager.mark_orphaned_sessions()

    cursor = await db.execute(
        "SELECT status, stopped_at, error_type, error_message FROM sessions WHERE id = ?",
        (crashed_session_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "failure", "status must stay 'failure', not be overwritten to 'unknown'"
    assert row[1] == pytest.approx(heartbeat_ts, abs=1), "stopped_at must be backfilled from last_heartbeat_at"
    assert row[2] == "ConnectionError", "error_type must be preserved"
    assert row[3] == "lost connection", "error_message must be preserved"


async def test_crashed_session_once_listeners_eligible_after_orphan_mark(
    session_manager: SessionManager, db_service: DatabaseService
) -> None:
    """once=True listeners from a crashed-then-killed session become cleanup-eligible after orphan-marking.

    End-to-end: insert a crashed session (status='failure', stopped_at NULL) with a fired once=True
    listener, orphan-mark it (backfills stopped_at), then run once-listener cleanup — the listener
    must be deleted.
    """
    db = db_service.db
    now = time.time()

    # Insert a crashed session with stopped_at NULL
    cursor = await db.execute(
        """
        INSERT INTO sessions (started_at, last_heartbeat_at, status, error_type, error_message)
        VALUES (?, ?, 'failure', 'RuntimeError', 'boom')
        """,
        (now - 600, now - 300),
    )
    await db.commit()
    crashed_session_id = cursor.lastrowid
    assert crashed_session_id is not None

    # Insert a once=True listener
    cursor = await db.execute(
        """
        INSERT INTO listeners
            (app_key, instance_index, name, handler_method, topic, once, source_location, source_tier)
        VALUES ('test_app', 0, 'crashed_once', 'on_event', 'test/topic', 1, 'test.py:1', 'app')
        """,
    )
    await db.commit()
    listener_id = cursor.lastrowid
    assert listener_id is not None

    # Insert an execution for that listener in the crashed session
    cursor = await db.execute(
        """
        INSERT INTO executions
            (kind, listener_id, session_id, execution_start_ts, duration_ms, status, source_tier)
        VALUES ('handler', ?, ?, ?, 5.0, 'success', 'app')
        """,
        (listener_id, crashed_session_id, now - 400),
    )
    await db.commit()

    # Before orphan-marking: stopped_at is NULL, so the liveness join treats it as live
    cursor = await db.execute("SELECT stopped_at FROM sessions WHERE id = ?", (crashed_session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "stopped_at must be NULL before orphan-marking"

    # Orphan-mark: backfills stopped_at
    await session_manager.mark_orphaned_sessions()

    cursor = await db.execute("SELECT stopped_at FROM sessions WHERE id = ?", (crashed_session_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "stopped_at must be backfilled after orphan-marking"

    # Create a current session so the cleanup has a live session to compare against
    await session_manager.create_session()

    # Run once-listener cleanup — the listener should now be eligible
    await session_manager.cleanup_stale_once_listeners()

    cursor = await db.execute("SELECT id FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is None, "once=True listener from crashed-then-orphaned session must be cleaned up"


def make_db_mock() -> MagicMock:
    """Build a mock DatabaseService that properly awaits coroutines passed to submit().

    on_service_crashed passes a coroutine to submit(); a plain AsyncMock accepts and
    discards it, leaving the coroutine un-awaited and triggering a
    PytestUnraisableExceptionWarning at GC time. This mock awaits whatever it receives.
    """
    db_mock = MagicMock()
    db_mock.is_db_ready = True
    db_mock.is_accepting_writes = True
    db_mock.db = AsyncMock()

    async def _submit(coro: object) -> None:
        if asyncio.iscoroutine(coro):
            await coro

    db_mock.submit = AsyncMock(side_effect=_submit)
    return db_mock


@pytest.mark.parametrize(
    ("role", "resource_name", "expect_error", "description"),
    [
        pytest.param(
            ResourceRole.APP,
            "MyBrokenApp",
            False,
            "APP-role crash must not mark the session as failed",
            id="app_role_filtered",
        ),
        pytest.param(
            ResourceRole.SERVICE,
            "WebSocketService",
            True,
            "SERVICE-role crash must mark the session as failed",
            id="service_role_passes",
        ),
    ],
)
async def test_crash_role_filter(
    test_config_class: type[HassetteConfig],
    unused_tcp_port_factory: "Callable[[], int]",
    role: ResourceRole,
    resource_name: str,
    expect_error: bool,
    description: str,
) -> None:
    """Regression test for #2153: only non-APP-role CRASHED events mark the session as failed.

    Exercises the IS_NOT_APP_ROLE predicate through a real Bus dispatch (not a direct handler
    call) — the existing fixture-based tests in this file call on_service_crashed directly and
    would not catch a bug in the ``where=`` filter itself.
    """
    # Isolated harness: same skip_global_set / build_harness pattern as
    # isolated_watcher() in test_service_watcher.py (see its docstring for why).
    config = test_config_class(web_api={"port": unused_tcp_port_factory()})
    harness = HassetteHarness(config, unused_tcp_port=unused_tcp_port_factory(), skip_global_set=True)
    async with build_harness(harness.with_bus()) as harness:
        hassette = harness.hassette

        sm = SessionManager(hassette, database_service=make_db_mock(), parent=hassette)
        sm._session_id = 1  # pretend a session was created
        await sm.on_initialize()

        await hassette.send_event(make_crashed_event(resource_name=resource_name, role=role))
        await hassette.bus_service.await_dispatch_idle()

        # Asserts on the in-memory flag rather than a DB row (the file's usual pattern)
        # because this test uses a mock DB — the point is verifying the bus-level where=
        # filter routes/blocks the event, not the persistence path.
        assert sm._session_error is expect_error, description
