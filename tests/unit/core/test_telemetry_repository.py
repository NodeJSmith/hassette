"""Unit tests for TelemetryRepository using an in-memory SQLite database."""

import sqlite3
import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_repository import TelemetryRepository
from hassette.scheduler.classes import JobExecutionRecord

# ---------------------------------------------------------------------------
# Schema DDL (mirrors migrations through 003 final state)
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
    source_tier           TEXT    NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework')),
    retired_at            REAL,
    immediate             INTEGER NOT NULL DEFAULT 0,
    duration              REAL,
    entity_id             TEXT
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
    trigger_type          TEXT
        CHECK (trigger_type IN ('interval', 'cron', 'once', 'after', 'custom')),
    trigger_label         TEXT    NOT NULL DEFAULT '',
    trigger_detail        TEXT,
    repeat                INTEGER NOT NULL DEFAULT 0,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    source_tier           TEXT    NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework')),
    retired_at            REAL,
    "group"               TEXT,
    cancelled_at          REAL
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
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
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
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
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
    """Provide an in-memory SQLite connection with the full schema applied and FK enforcement on."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
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


def _make_job_registration(*, job_name: str = "test_job", group: str | None = None) -> ScheduledJobRegistration:
    return ScheduledJobRegistration(
        app_key="test_app",
        instance_index=0,
        job_name=job_name,
        handler_method="test_app.my_job",
        trigger_type=None,
        trigger_label="once",
        trigger_detail=None,
        args_json="[]",
        kwargs_json="{}",
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
        group=group,
    )


# ---------------------------------------------------------------------------
# register_listener tests
# ---------------------------------------------------------------------------


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


async def test_register_job_persists_group(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() writes the group value to the database."""
    reg = _make_job_registration(job_name="morning_job", group="morning")
    job_id = await repo.register_job(reg)

    cursor = await db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "morning", f"Expected group='morning', got {row[0]!r}"


async def test_register_job_persists_null_group(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() persists NULL for group when group is not set."""
    reg = _make_job_registration()
    job_id = await repo.register_job(reg)

    cursor = await db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, f"Expected group=None, got {row[0]!r}"


async def test_mark_job_cancelled_sets_cancelled_at(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """mark_job_cancelled() sets cancelled_at to the current epoch time."""
    reg = _make_job_registration(job_name="cancellable_job")
    job_id = await repo.register_job(reg)

    # Verify cancelled_at is NULL before marking
    cursor = await db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "cancelled_at should be NULL before cancellation"

    # Mark cancelled and verify the timestamp is set
    before_ts = time.time()
    await repo.mark_job_cancelled(job_id)
    after_ts = time.time()

    cursor = await db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "cancelled_at should be set after mark_job_cancelled()"
    assert before_ts <= row[0] <= after_ts, f"cancelled_at={row[0]} should be between {before_ts} and {after_ts}"


# ---------------------------------------------------------------------------
# reconcile_registrations tests
# ---------------------------------------------------------------------------


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


async def test_reconcile_empty_ids_no_crash(
    repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    # Should not raise
    await repo.reconcile_registrations("test_app", [], [])


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


async def test_upsert_same_natural_key_returns_same_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with same natural key returns the same ID (upsert)."""
    reg = _make_listener_registration()
    id1 = await repo.register_listener(reg)
    id2 = await repo.register_listener(reg)
    assert id1 == id2


async def test_upsert_different_natural_key_returns_new_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with different topic returns a new ID."""
    id1 = await repo.register_listener(_make_listener_registration(topic="topic.a"))
    id2 = await repo.register_listener(_make_listener_registration(topic="topic.b"))
    assert id1 != id2


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


async def test_schema_has_name_column(db: aiosqlite.Connection) -> None:
    """Migration 006: listeners table includes the name column."""
    cursor = await db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    column_names = [row["name"] for row in rows]
    assert "name" in column_names


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


async def test_active_views_exist(db: aiosqlite.Connection) -> None:
    """Migration 006: SELECT * FROM active_listeners and active_scheduled_jobs succeeds."""
    cursor = await db.execute("SELECT * FROM active_listeners")
    rows = await cursor.fetchall()
    assert rows == []  # empty DB

    cursor = await db.execute("SELECT * FROM active_scheduled_jobs")
    rows = await cursor.fetchall()
    assert rows == []  # empty DB


# ---------------------------------------------------------------------------
# reconcile_registrations — live_job_ids non-empty paths (lines 337-338, 362-363)
# ---------------------------------------------------------------------------


async def test_reconcile_deletes_stale_job_not_in_live_set(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale jobs NOT in live_job_ids when live_job_ids is non-empty."""
    job_id_a = await repo.register_job(_make_job_registration(job_name="job_a"))
    job_id_b = await repo.register_job(_make_job_registration(job_name="job_b"))

    # Keep job_a live, let job_b be stale (no history → deleted)
    await repo.reconcile_registrations("test_app", [], [job_id_a])

    cursor = await db.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE id = ?", (job_id_a,))
    row = await cursor.fetchone()
    assert row[0] == 1, "Live job should be preserved"

    cursor = await db.execute("SELECT COUNT(*) FROM scheduled_jobs WHERE id = ?", (job_id_b,))
    row = await cursor.fetchone()
    assert row[0] == 0, "Stale job without history should be deleted (non-empty live_job_ids branch)"


async def test_reconcile_retires_stale_job_with_history_non_empty_live_set(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """reconcile_registrations() retires stale jobs with history when live_job_ids is non-empty."""
    job_id_a = await repo.register_job(_make_job_registration(job_name="job_a"))
    job_id_b = await repo.register_job(_make_job_registration(job_name="job_b"))

    # Give job_b some history so it gets retired rather than deleted
    await db.execute(
        "INSERT INTO job_executions (job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id_b, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    # Keep job_a live, job_b is stale with history → retired
    await repo.reconcile_registrations("test_app", [], [job_id_a])

    cursor = await db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id_b,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Stale job with history should have retired_at set (non-empty live_job_ids branch)"

    cursor = await db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id_a,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "Live job should not be retired"


async def test_reconcile_once_true_delete_non_empty_live_listener_ids(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True listeners not in live IDs when live_listener_ids is non-empty."""
    # Register a regular (once=False) listener to populate live_listener_ids
    live_reg = _make_listener_registration(topic="topic.live")
    live_id = await repo.register_listener(live_reg)

    # Register a once=True listener from a previous session
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

    # Use a new session (once_id has no invocations in new_session)
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

    # Reconcile with live_id in live set — exercises the non-empty live_listener_ids once=True branch
    await repo.reconcile_registrations("test_app", [live_id], [], session_id=new_session_id)

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row[0] == 0, (
        "once=True listener from previous session should be deleted (non-empty live_listener_ids branch)"
    )

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (live_id,))
    row = await cursor.fetchone()
    assert row[0] == 1, "Live listener should be preserved"


async def test_reconcile_rollback_on_exception(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() rolls back the transaction on unexpected errors (lines 388-390)."""
    # Patch db.execute to raise after the first call succeeds
    original_execute = db.execute
    call_count = 0

    async def failing_execute(sql, params=None):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise RuntimeError("simulated DB error")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with (
        patch.object(db, "execute", side_effect=failing_execute),
        pytest.raises(RuntimeError, match="simulated DB error"),
    ):
        await repo.reconcile_registrations("test_app", [], [])


# ---------------------------------------------------------------------------
# persist_batch_with_fk_fallback tests (lines 405-525)
# ---------------------------------------------------------------------------


async def test_persist_batch_with_fk_fallback_success_path(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() inserts records when no FK violations occur."""
    listener_id = await repo.register_listener(_make_listener_registration())
    job_id = await repo.register_job(_make_job_registration())

    now = time.time()
    invocation = HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )
    job_exec = JobExecutionRecord(
        job_id=job_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await repo.persist_batch_with_fk_fallback([invocation], [job_exec])

    assert dropped == 0

    cursor = await db.execute("SELECT listener_id FROM handler_invocations WHERE listener_id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == listener_id

    cursor = await db.execute("SELECT job_id FROM job_executions WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == job_id


async def test_persist_batch_with_fk_fallback_nulls_listener_fk_on_violation(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() nulls listener_id on FK violation and still inserts."""
    now = time.time()
    # Use a listener_id that does not exist in the DB
    bad_listener_id = 99999
    invocation = HandlerInvocationRecord(
        listener_id=bad_listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    dropped = await repo.persist_batch_with_fk_fallback([invocation], [])

    assert dropped == 0

    # Row should exist with listener_id = NULL
    cursor = await db.execute("SELECT listener_id FROM handler_invocations")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "listener_id should be nulled after FK violation"


async def test_persist_batch_with_fk_fallback_nulls_job_fk_on_violation(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() nulls job_id on FK violation and still inserts."""
    now = time.time()
    bad_job_id = 99999
    job_exec = JobExecutionRecord(
        job_id=bad_job_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await repo.persist_batch_with_fk_fallback([], [job_exec])

    assert dropped == 0

    cursor = await db.execute("SELECT job_id FROM job_executions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "job_id should be nulled after FK violation"


async def test_persist_batch_with_fk_fallback_drops_row_on_second_failure(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() increments dropped count when null-FK retry also fails."""
    now = time.time()
    invocation = HandlerInvocationRecord(
        listener_id=None,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    original_execute = db.execute
    call_count = 0

    # Simulate the first INSERT raising IntegrityError, then the second (null-FK) also failing
    async def patched_execute(sql, params=None):
        nonlocal call_count
        if "INSERT INTO handler_invocations" in sql:
            call_count += 1
            if call_count == 1:
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            if call_count == 2:
                raise sqlite3.IntegrityError("NOT NULL constraint failed on null-FK retry")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with patch.object(db, "execute", side_effect=patched_execute):
        dropped = await repo.persist_batch_with_fk_fallback([invocation], [])

    assert dropped == 1, "Row that fails even with null FK should be counted as dropped"


async def test_persist_batch_with_fk_fallback_drops_job_row_on_second_failure(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() increments dropped count for job_executions when null-FK retry fails."""
    now = time.time()
    job_exec = JobExecutionRecord(
        job_id=None,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    original_execute = db.execute
    call_count = 0

    async def patched_execute(sql, params=None):
        nonlocal call_count
        if "INSERT INTO job_executions" in sql:
            call_count += 1
            if call_count == 1:
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            if call_count == 2:
                raise sqlite3.IntegrityError("NOT NULL constraint failed on null-FK retry")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with patch.object(db, "execute", side_effect=patched_execute):
        dropped = await repo.persist_batch_with_fk_fallback([], [job_exec])

    assert dropped == 1, "Job row that fails even with null FK should be counted as dropped"


async def test_persist_batch_with_fk_fallback_empty_lists(
    repo: TelemetryRepository,
) -> None:
    """persist_batch_with_fk_fallback() with empty lists returns 0 dropped."""
    dropped = await repo.persist_batch_with_fk_fallback([], [])
    assert dropped == 0


async def test_persist_batch_with_fk_fallback_rollback_on_exception(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch_with_fk_fallback() rolls back on unexpected errors (lines 521-523)."""
    now = time.time()
    invocation = HandlerInvocationRecord(
        listener_id=None,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    original_execute = db.execute

    async def patched_execute(sql, params=None):
        if "BEGIN" in sql:
            raise RuntimeError("simulated connection failure")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with (
        patch.object(db, "execute", side_effect=patched_execute),
        pytest.raises(RuntimeError, match="simulated connection failure"),
    ):
        await repo.persist_batch_with_fk_fallback([invocation], [])


# ---------------------------------------------------------------------------
# persist_batch exception path (lines 602-604)
# ---------------------------------------------------------------------------


async def test_persist_batch_rollback_on_exception(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_batch() rolls back and re-raises on unexpected error (lines 602-604)."""
    listener_id = await repo.register_listener(_make_listener_registration())
    now = time.time()
    invocation = HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    async def failing_executemany(_sql, _params):
        raise RuntimeError("simulated executemany failure")

    with (
        patch.object(db, "executemany", side_effect=failing_executemany),
        pytest.raises(RuntimeError, match="simulated executemany failure"),
    ):
        await repo.persist_batch([invocation], [])

    # Confirm the row was not committed
    cursor = await db.execute("SELECT COUNT(*) FROM handler_invocations")
    row = await cursor.fetchone()
    assert row[0] == 0, "No rows should be committed after rollback"
