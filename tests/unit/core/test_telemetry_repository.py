"""Unit tests for TelemetryRepository using an in-memory SQLite database."""

import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import aiosqlite
import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.scheduler.classes import JobExecutionRecord

# ---------------------------------------------------------------------------
# Schema DDL (mirrors migrations 001-006 final state)
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE sessions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at            REAL    NOT NULL,
    stopped_at            REAL,
    last_heartbeat_at     REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT
);

CREATE TABLE listeners (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    handler_method        TEXT    NOT NULL,
    topic                 TEXT    NOT NULL,
    debounce              REAL,
    throttle              REAL,
    once                  INTEGER NOT NULL DEFAULT 0,
    priority              INTEGER NOT NULL DEFAULT 0,
    predicate_description TEXT,
    human_description     TEXT,
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    name                  TEXT,
    retired_at            REAL
);

CREATE UNIQUE INDEX idx_listeners_natural
    ON listeners(app_key, instance_index, handler_method, topic, COALESCE(name, human_description, ''))
    WHERE once = 0;

CREATE INDEX idx_listeners_app ON listeners(app_key, instance_index);

CREATE TABLE scheduled_jobs (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    app_key               TEXT    NOT NULL,
    instance_index        INTEGER NOT NULL,
    job_name              TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    trigger_type          TEXT,
    trigger_value         TEXT,
    repeat                INTEGER NOT NULL DEFAULT 0,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    retired_at            REAL
);

CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index);

CREATE TABLE handler_invocations (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT
);

CREATE INDEX idx_hi_listener_time ON handler_invocations(listener_id, execution_start_ts DESC);
CREATE INDEX idx_hi_status_time ON handler_invocations(status, execution_start_ts DESC);
CREATE INDEX idx_hi_time ON handler_invocations(execution_start_ts);
CREATE INDEX idx_hi_session ON handler_invocations(session_id);


CREATE TABLE job_executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT
);

CREATE INDEX idx_je_job_time ON job_executions(job_id, execution_start_ts DESC);
CREATE INDEX idx_je_status_time ON job_executions(status, execution_start_ts DESC);
CREATE INDEX idx_je_time ON job_executions(execution_start_ts);
CREATE INDEX idx_je_session ON job_executions(session_id);

CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL;

CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL;
"""

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    """Provide an in-memory SQLite connection with the full schema applied."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.executescript(_DDL)
        await conn.commit()
        yield conn


@pytest.fixture
async def repo(db: aiosqlite.Connection) -> TelemetryRepository:
    """Create a TelemetryRepository backed by an in-memory SQLite connection."""
    mock_db_service = MagicMock()
    mock_db_service.db = db
    return TelemetryRepository(mock_db_service)


@pytest.fixture
async def session_id(db: aiosqlite.Connection) -> int:
    """Insert a session row and return its ID (needed for FK constraints)."""
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def _make_listener_registration(*, topic: str = "hass.event.state_changed") -> ListenerRegistration:
    return ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic=topic,
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
    )


def _make_job_registration(*, job_name: str = "test_job") -> ScheduledJobRegistration:
    return ScheduledJobRegistration(
        app_key="test_app",
        instance_index=0,
        job_name=job_name,
        handler_method="test_app.my_job",
        trigger_type=None,
        trigger_value=None,
        repeat=False,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
    )


# ---------------------------------------------------------------------------
# register_listener tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_listener_inserts_and_returns_id(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_listener() inserts a row and returns a valid positive integer ID."""
    reg = _make_listener_registration()
    listener_id = await repo.register_listener(reg)

    assert isinstance(listener_id, int)
    assert listener_id > 0

    cursor = await db.execute("SELECT id, app_key, topic FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == "test_app"
    assert row["topic"] == "hass.event.state_changed"


# ---------------------------------------------------------------------------
# register_job tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_job_inserts_and_returns_id(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() inserts a row and returns a valid positive integer ID."""
    reg = _make_job_registration()
    job_id = await repo.register_job(reg)

    assert isinstance(job_id, int)
    assert job_id > 0

    cursor = await db.execute("SELECT id, app_key, job_name FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == "test_app"
    assert row["job_name"] == "test_job"


# ---------------------------------------------------------------------------
# reconcile_registrations tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconcile_deletes_stale_without_history(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale non-once listeners with no invocation history."""
    listener_id = await repo.register_listener(_make_listener_registration())
    job_id = await repo.register_job(_make_job_registration())

    # Reconcile with empty live IDs — the rows have no history, so they should be deleted
    await repo.reconcile_registrations("test_app", [], [])

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row[0] == 0, "Stale listener without history should be deleted"

    cursor = await db.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row[0] == 0, "Stale job without history should be deleted"


@pytest.mark.asyncio
async def test_reconcile_retires_stale_with_history(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """reconcile_registrations() sets retired_at on stale rows that have invocation history."""
    listener_id = await repo.register_listener(_make_listener_registration())
    job_id = await repo.register_job(_make_job_registration())

    # Create history for both
    await db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db.execute(
        "INSERT INTO job_executions (job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    # Reconcile with empty live IDs — rows have history so they should be retired
    await repo.reconcile_registrations("test_app", [], [])

    cursor = await db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Stale listener with history should have retired_at set"

    cursor = await db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Stale job with history should have retired_at set"


@pytest.mark.asyncio
async def test_reconcile_preserves_live_listeners(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() preserves listeners whose IDs are in the live set."""
    reg_a = _make_listener_registration(topic="topic.a")
    reg_b = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event_b",
        topic="topic.b",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
    )
    id_a = await repo.register_listener(reg_a)
    id_b = await repo.register_listener(reg_b)

    # Reconcile — keep id_a live, let id_b be stale (no history so it's deleted)
    await repo.reconcile_registrations("test_app", [id_a], [])

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (id_a,))
    row = await cursor.fetchone()
    assert row[0] == 1, "Live listener should be preserved"

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (id_b,))
    row = await cursor.fetchone()
    assert row[0] == 0, "Stale listener without history should be deleted"


@pytest.mark.asyncio
@pytest.mark.usefixtures("session_id")
async def test_reconcile_deletes_once_true_previous_session(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True rows from previous sessions (no current invocations)."""
    # Register a once=True listener (always inserts fresh)
    once_reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=True,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
    )
    once_id = await repo.register_listener(once_reg)

    # Use a different session_id for current reconciliation to simulate a new session
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

    # Reconcile with new session — once_id should be deleted (no current session invocations)
    await repo.reconcile_registrations("test_app", [], [], session_id=new_session_id)

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row[0] == 0, "once=True listener from previous session should be deleted"


@pytest.mark.asyncio
async def test_reconcile_preserves_once_true_with_current_invocations(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """reconcile_registrations() preserves once=True rows that have current-session invocations."""
    once_reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=True,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test.py:1",
        registration_source=None,
    )
    once_id = await repo.register_listener(once_reg)

    # Create an invocation in the CURRENT session
    await db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (once_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    # Reconcile with current session_id — once row has current invocations so it should be preserved
    await repo.reconcile_registrations("test_app", [], [], session_id=session_id)

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row[0] == 1, "once=True listener with current-session invocations should be preserved"


@pytest.mark.asyncio
async def test_reconcile_empty_ids_no_crash(
    repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    # Should not raise
    await repo.reconcile_registrations("test_app", [], [])


@pytest.mark.asyncio
async def test_reconcile_resets_retired_at_on_reupsert(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """After a row is retired, re-upserting it (same natural key) resets retired_at to NULL."""
    reg = _make_listener_registration()
    listener_id = await repo.register_listener(reg)

    # Create history so reconciliation retires rather than deletes
    await db.execute(
        "INSERT INTO handler_invocations (listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    # Reconcile with empty set — retires the row
    await repo.reconcile_registrations("test_app", [], [])

    cursor = await db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Row should be retired after reconciliation"

    # Re-upsert the same natural key — should reset retired_at to NULL and return same ID
    new_id = await repo.register_listener(reg)
    assert new_id == listener_id, "Re-upsert should return the same ID"

    cursor = await db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "retired_at should be reset to NULL after re-upsert"


# ---------------------------------------------------------------------------
# Upsert contract tests (WP04)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_same_natural_key_returns_same_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with same natural key returns the same ID (upsert)."""
    reg = _make_listener_registration()
    id1 = await repo.register_listener(reg)
    id2 = await repo.register_listener(reg)
    assert id1 == id2


@pytest.mark.asyncio
async def test_upsert_different_natural_key_returns_new_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with different topic returns a new ID."""
    id1 = await repo.register_listener(_make_listener_registration(topic="topic.a"))
    id2 = await repo.register_listener(_make_listener_registration(topic="topic.b"))
    assert id1 != id2


@pytest.mark.asyncio
async def test_upsert_updates_mutable_fields(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """Upsert updates debounce (mutable field) on conflict."""
    reg = _make_listener_registration()
    listener_id = await repo.register_listener(reg)

    updated_reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=5.0,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_telemetry_repository.py:99",
        registration_source=None,
    )
    id2 = await repo.register_listener(updated_reg)
    assert id2 == listener_id

    cursor = await db.execute("SELECT debounce FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 5.0


@pytest.mark.asyncio
async def test_once_true_always_inserts(
    repo: TelemetryRepository,
) -> None:
    """once=True listeners always get a new row (no upsert)."""
    reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=True,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
    )
    id1 = await repo.register_listener(reg)
    id2 = await repo.register_listener(reg)
    assert id1 != id2


@pytest.mark.asyncio
async def test_upsert_does_not_update_human_description(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """human_description is part of the key and is NOT updated on upsert."""
    reg = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description="entity light.kitchen",
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
    )
    listener_id = await repo.register_listener(reg)

    # Re-register with same key — source_location is mutable, human_description is identity
    reg2 = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description="entity light.kitchen",
        source_location="test_telemetry_repository.py:99",
        registration_source=None,
    )
    id2 = await repo.register_listener(reg2)
    assert id2 == listener_id

    cursor = await db.execute("SELECT human_description FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "entity light.kitchen"


@pytest.mark.asyncio
async def test_upsert_with_name_overrides_key(
    repo: TelemetryRepository,
) -> None:
    """Two listeners with same handler+topic but different name= get different IDs."""
    reg_a = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
        name="listener_a",
    )
    reg_b = ListenerRegistration(
        app_key="test_app",
        instance_index=0,
        handler_method="test_app.on_event",
        topic="hass.event.state_changed",
        debounce=None,
        throttle=None,
        once=False,
        priority=0,
        predicate_description=None,
        human_description=None,
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
        name="listener_b",
    )
    id_a = await repo.register_listener(reg_a)
    id_b = await repo.register_listener(reg_b)
    assert id_a != id_b


# ---------------------------------------------------------------------------
# persist_batch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persist_batch_inserts_handler_invocations(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch() inserts handler invocation records into handler_invocations."""
    listener_id = await repo.register_listener(_make_listener_registration())

    now = time.time()
    records = [
        HandlerInvocationRecord(
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=now,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
        ),
        HandlerInvocationRecord(
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=now + 1,
            duration_ms=10.0,
            status="error",
            error_type="ValueError",
            error_message="oops",
            error_traceback="Traceback...",
        ),
    ]

    await repo.persist_batch(records, [])

    cursor = await db.execute(
        "SELECT status, duration_ms FROM handler_invocations WHERE listener_id = ? ORDER BY execution_start_ts",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "success"
    assert rows[1]["status"] == "error"


@pytest.mark.asyncio
async def test_persist_batch_inserts_job_executions(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch() inserts job execution records into job_executions."""
    job_id = await repo.register_job(_make_job_registration())

    now = time.time()
    records = [
        JobExecutionRecord(
            job_id=job_id,
            session_id=session_id,
            execution_start_ts=now,
            duration_ms=20.0,
            status="success",
        ),
    ]

    await repo.persist_batch([], records)

    cursor = await db.execute(
        "SELECT status, job_id FROM job_executions WHERE job_id = ?",
        (job_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["job_id"] == job_id


@pytest.mark.asyncio
async def test_persist_batch_handles_empty_lists(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """persist_batch() with empty lists completes without error and inserts nothing."""
    await repo.persist_batch([], [])

    cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
    row = await cursor.fetchone()
    assert row[0] == 0

    cursor = await db.execute("SELECT COUNT(*) FROM job_executions")
    row = await cursor.fetchone()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# Migration 006 schema tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_has_name_column(db: aiosqlite.Connection) -> None:
    """Migration 006: listeners table includes the name column."""
    cursor = await db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    column_names = [row["name"] for row in rows]
    assert "name" in column_names


@pytest.mark.asyncio
async def test_schema_has_retired_at_column(db: aiosqlite.Connection) -> None:
    """Migration 006: both listeners and scheduled_jobs have a retired_at column."""
    cursor = await db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    listener_columns = [row["name"] for row in rows]
    assert "retired_at" in listener_columns

    cursor = await db.execute("PRAGMA table_info(scheduled_jobs)")
    rows = await cursor.fetchall()
    job_columns = [row["name"] for row in rows]
    assert "retired_at" in job_columns


@pytest.mark.asyncio
async def test_unique_index_enforced(db: aiosqlite.Connection) -> None:
    """Migration 006: two non-once listeners with same natural key raises IntegrityError."""
    sql = """
        INSERT INTO listeners
            (app_key, instance_index, handler_method, topic, once, priority, source_location)
        VALUES ('app', 0, 'app.handler', 'light.on', 0, 0, 'app.py:1')
    """
    await db.execute(sql)
    await db.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(sql)


@pytest.mark.asyncio
async def test_partial_index_allows_once_duplicates(db: aiosqlite.Connection) -> None:
    """Migration 006: two once=1 listeners with same natural key succeeds (partial index)."""
    sql = """
        INSERT INTO listeners
            (app_key, instance_index, handler_method, topic, once, priority, source_location)
        VALUES ('app', 0, 'app.handler', 'light.on', 1, 0, 'app.py:1')
    """
    await db.execute(sql)
    await db.execute(sql)
    await db.commit()

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE once = 1 AND handler_method = 'app.handler'")
    row = await cursor.fetchone()
    assert row[0] == 2


@pytest.mark.asyncio
async def test_active_views_exist(db: aiosqlite.Connection) -> None:
    """Migration 006: SELECT * FROM active_listeners and active_scheduled_jobs succeeds."""
    cursor = await db.execute("SELECT * FROM active_listeners")
    rows = await cursor.fetchall()
    assert rows == []  # empty DB

    cursor = await db.execute("SELECT * FROM active_scheduled_jobs")
    rows = await cursor.fetchall()
    assert rows == []  # empty DB
