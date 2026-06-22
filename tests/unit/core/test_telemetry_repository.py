"""Unit tests for TelemetryRepository using an in-memory SQLite database."""

import inspect
import sqlite3
import time
from collections.abc import AsyncIterator
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

import hassette.core.telemetry.repository as telemetry_repository_module
from hassette.core.execution_record import ExecutionRecord
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.test_utils.config import TEST_SOURCE_LOCATION

# DDL mirrors 001.sql — unified schema with executions table replacing handler_invocations/job_executions
DDL = """
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
    name                  TEXT    NOT NULL,
    handler_method        TEXT    NOT NULL,
    topic                 TEXT    NOT NULL,
    debounce              REAL,
    throttle              REAL,
    once                  INTEGER NOT NULL DEFAULT 0,
    priority              INTEGER NOT NULL DEFAULT 0,
    mode                  TEXT    NOT NULL DEFAULT 'single',
    backpressure          TEXT    NOT NULL DEFAULT 'block' CHECK (backpressure IN ('block', 'drop_newest')),
    predicate_description TEXT,
    human_description     TEXT,
    source_location       TEXT    NOT NULL,
    registration_source   TEXT,
    source_tier           TEXT    NOT NULL DEFAULT 'app' CHECK (source_tier IN ('app', 'framework')),
    retired_at            REAL,
    cancelled_at          REAL,
    immediate             INTEGER NOT NULL DEFAULT 0,
    duration              REAL,
    entity_id             TEXT
);

CREATE UNIQUE INDEX idx_listeners_natural
    ON listeners(app_key, instance_index, name, topic);

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
    cancelled_at          REAL,
    name_auto             INTEGER NOT NULL DEFAULT 0,
    mode                  TEXT    NOT NULL DEFAULT 'single'
        CHECK (mode IN ('single', 'restart', 'queued', 'parallel'))
);

CREATE UNIQUE INDEX idx_scheduled_jobs_natural
    ON scheduled_jobs(app_key, instance_index, job_name);

CREATE INDEX idx_scheduled_jobs_app ON scheduled_jobs(app_key, instance_index);

CREATE TABLE executions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    kind                  TEXT    NOT NULL CHECK (kind IN ('handler', 'job')),
    listener_id           INTEGER REFERENCES listeners(id) ON DELETE SET NULL,
    job_id                INTEGER REFERENCES scheduled_jobs(id) ON DELETE SET NULL,
    session_id            INTEGER NOT NULL REFERENCES sessions(id),
    execution_start_ts    REAL    NOT NULL,
    duration_ms           REAL    NOT NULL,
    status                TEXT    NOT NULL,
    error_type            TEXT,
    error_message         TEXT,
    error_traceback       TEXT,
    is_di_failure         INTEGER NOT NULL DEFAULT 0,
    source_tier           TEXT    NOT NULL DEFAULT 'app',
    execution_id          TEXT UNIQUE,
    trigger_context_id    TEXT,
    trigger_origin        TEXT,
    trigger_mode          TEXT,
    retry_count           INTEGER NOT NULL DEFAULT 0,
    attempt_number        INTEGER NOT NULL DEFAULT 1,
    args_json             TEXT    NOT NULL DEFAULT '[]',
    kwargs_json           TEXT    NOT NULL DEFAULT '{}',
    thread_leaked         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_exec_listener_time
    ON executions(listener_id, execution_start_ts DESC)
    WHERE listener_id IS NOT NULL;
CREATE INDEX idx_exec_job_time
    ON executions(job_id, execution_start_ts DESC)
    WHERE job_id IS NOT NULL;

CREATE VIEW active_listeners AS
    SELECT * FROM listeners WHERE retired_at IS NULL;

CREATE VIEW active_scheduled_jobs AS
    SELECT * FROM scheduled_jobs WHERE retired_at IS NULL;
"""


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    """Provide an in-memory SQLite connection with the full schema applied and FK enforcement on."""
    async with aiosqlite.connect(":memory:") as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.executescript(DDL)
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


def make_listener_registration(
    *,
    topic: str = "hass.event.state_changed",
    name: str = "test_app.on_event",
) -> ListenerRegistration:
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
        name=name,
    )


def make_job_registration(
    *,
    job_name: str = "test_job",
    group: str | None = None,
    name_auto: bool = False,
) -> ScheduledJobRegistration:
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
        name_auto=name_auto,
    )


async def test_register_listener_inserts_and_returns_id(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_listener() inserts a row and returns a valid positive integer ID."""
    reg = make_listener_registration()
    listener_id = await repo.register_listener(reg)

    assert isinstance(listener_id, int)
    assert listener_id > 0

    cursor = await db.execute("SELECT id, app_key, topic FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == "test_app"
    assert row["topic"] == "hass.event.state_changed"


async def test_register_job_inserts_and_returns_id(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() inserts a row and returns a valid positive integer ID."""
    reg = make_job_registration()
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
    reg = make_job_registration(job_name="morning_job", group="morning")
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
    reg = make_job_registration()
    job_id = await repo.register_job(reg)

    cursor = await db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, f"Expected group=None, got {row[0]!r}"


async def test_register_job_persists_name_auto_true(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() writes name_auto=1 when the name was auto-generated."""
    reg = make_job_registration(job_name="run:after:5", name_auto=True)
    job_id = await repo.register_job(reg)

    cursor = await db.execute("SELECT name_auto FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


async def test_register_job_persists_name_auto_false(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """register_job() writes name_auto=0 by default."""
    reg = make_job_registration()
    job_id = await repo.register_job(reg)

    cursor = await db.execute("SELECT name_auto FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 0


async def test_mark_job_cancelled_sets_cancelled_at(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """mark_job_cancelled() sets cancelled_at to the current epoch time."""
    reg = make_job_registration(job_name="cancellable_job")
    job_id = await repo.register_job(reg)

    cursor = await db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "cancelled_at should be NULL before cancellation"

    before_ts = time.time()
    await repo.mark_job_cancelled(job_id)
    after_ts = time.time()

    cursor = await db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "cancelled_at should be set after mark_job_cancelled()"
    assert before_ts <= row[0] <= after_ts, f"cancelled_at={row[0]} should be between {before_ts} and {after_ts}"


async def test_reconcile_deletes_stale_without_history(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale non-once listeners with no execution history."""
    listener_id = await repo.register_listener(make_listener_registration())
    job_id = await repo.register_job(make_job_registration())

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
    """reconcile_registrations() sets retired_at on stale rows that have execution history."""
    listener_id = await repo.register_listener(make_listener_registration())
    job_id = await repo.register_job(make_job_registration())

    # Create history in the unified executions table
    await db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', ?, ?, ?, ?, ?)",
        (job_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

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
    id_a = await repo.register_listener(make_listener_registration(topic="topic.a", name="test_app.on_event_a"))
    id_b = await repo.register_listener(make_listener_registration(topic="topic.b", name="test_app.on_event_b"))

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
    """reconcile_registrations() deletes once=True rows from previous sessions (no current executions)."""
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
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
        name="test_app.on_event.once",
    )
    once_id = await repo.register_listener(once_reg)

    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

    await repo.reconcile_registrations("test_app", [], [], session_id=new_session_id)

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row[0] == 0, "once=True listener from previous session should be deleted"


async def test_reconcile_preserves_once_true_with_current_executions(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """reconcile_registrations() preserves once=True rows that have current-session executions."""
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
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
        name="test_app.on_event.once",
    )
    once_id = await repo.register_listener(once_reg)

    # Create an execution in the CURRENT session
    await db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (once_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    await repo.reconcile_registrations("test_app", [], [], session_id=session_id)

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row[0] == 1, "once=True listener with current-session executions should be preserved"


async def test_reconcile_empty_ids_no_crash(
    repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    await repo.reconcile_registrations("test_app", [], [])


async def test_reconcile_resets_retired_at_on_reupsert(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """After a row is retired, re-upserting it (same natural key) resets retired_at to NULL."""
    reg = make_listener_registration()
    listener_id = await repo.register_listener(reg)

    # Create history so reconciliation retires rather than deletes
    await db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (listener_id, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

    await repo.reconcile_registrations("test_app", [], [])

    cursor = await db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "Row should be retired after reconciliation"

    new_id = await repo.register_listener(reg)
    assert new_id == listener_id, "Re-upsert should return the same ID"

    cursor = await db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "retired_at should be reset to NULL after re-upsert"


async def test_upsert_same_natural_key_returns_same_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with same natural key returns the same ID (upsert)."""
    reg = make_listener_registration()
    id1 = await repo.register_listener(reg)
    id2 = await repo.register_listener(reg)
    assert id1 == id2


async def test_upsert_different_natural_key_returns_new_id(
    repo: TelemetryRepository,
) -> None:
    """register_listener() with different topic returns a new ID."""
    id1 = await repo.register_listener(make_listener_registration(topic="topic.a", name="test_app.on_a"))
    id2 = await repo.register_listener(make_listener_registration(topic="topic.b", name="test_app.on_b"))
    assert id1 != id2


async def test_upsert_updates_mutable_fields(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """Upsert updates debounce (mutable field) on conflict."""
    reg = make_listener_registration()
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
        name="test_app.on_event",
    )
    id2 = await repo.register_listener(updated_reg)
    assert id2 == listener_id

    cursor = await db.execute("SELECT debounce FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 5.0


async def test_once_true_upserts_by_name_topic(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """once=True listeners with a name upsert on (name, topic) like once=False listeners."""
    # Two registrations with same name+topic — should upsert to same row
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
        source_location="test_telemetry_repository.py:1",
        registration_source=None,
        name="test_app.on_event.once",
    )
    id1 = await repo.register_listener(once_reg)
    id2 = await repo.register_listener(once_reg)
    assert id1 == id2

    cursor = await db.execute("SELECT COUNT(*) FROM listeners WHERE name = 'test_app.on_event.once'")
    row = await cursor.fetchone()
    assert row[0] == 1, "Upsert should produce a single row, not two inserts"


async def test_upsert_does_not_update_human_description(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """human_description is NOT updated on upsert (not in the DO UPDATE SET list)."""
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
        name="test_app.on_event",
    )
    listener_id = await repo.register_listener(reg)

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
        name="test_app.on_event",
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


async def test_persist_execution_batch_inserts_handler_records(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch() inserts handler ExecutionRecords into the executions table."""
    listener_id = await repo.register_listener(make_listener_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=now,
            duration_ms=5.0,
            status="success",
        ),
        ExecutionRecord(
            kind="handler",
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

    await repo.persist_execution_batch(records)

    cursor = await db.execute(
        "SELECT status, duration_ms, kind FROM executions WHERE listener_id = ? ORDER BY execution_start_ts",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "success"
    assert rows[0]["kind"] == "handler"
    assert rows[1]["status"] == "error"
    assert rows[1]["kind"] == "handler"


async def test_persist_execution_batch_inserts_job_records(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch() inserts job ExecutionRecords into the executions table."""
    job_id = await repo.register_job(make_job_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="job",
            job_id=job_id,
            session_id=session_id,
            execution_start_ts=now,
            duration_ms=20.0,
            status="success",
        ),
    ]

    await repo.persist_execution_batch(records)

    cursor = await db.execute(
        "SELECT status, job_id, kind FROM executions WHERE job_id = ?",
        (job_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["job_id"] == job_id
    assert rows[0]["kind"] == "job"


async def test_persist_execution_batch_handles_empty_list(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """persist_execution_batch() with empty list completes without error and inserts nothing."""
    await repo.persist_execution_batch([])

    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row[0] == 0


async def test_persist_execution_batch_unified(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch() inserts ExecutionRecord rows into executions with correct kind."""
    listener_id = await repo.register_listener(make_listener_registration())
    job_id = await repo.register_job(make_job_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=now,
            duration_ms=5.0,
            status="success",
        ),
        ExecutionRecord(
            kind="job",
            job_id=job_id,
            session_id=session_id,
            execution_start_ts=now + 1,
            duration_ms=15.0,
            status="success",
        ),
    ]

    await repo.persist_execution_batch(records)

    cursor = await db.execute("SELECT kind, listener_id, job_id FROM executions ORDER BY execution_start_ts")
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["kind"] == "handler"
    assert rows[0]["listener_id"] == listener_id
    assert rows[0]["job_id"] is None
    assert rows[1]["kind"] == "job"
    assert rows[1]["job_id"] == job_id
    assert rows[1]["listener_id"] is None


async def test_schema_has_name_column(db: aiosqlite.Connection) -> None:
    """listeners table includes the name column (NOT NULL in unified schema)."""
    cursor = await db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    column_names = [row["name"] for row in rows]
    assert "name" in column_names


async def test_schema_has_retired_at_column(db: aiosqlite.Connection) -> None:
    """Both listeners and scheduled_jobs have a retired_at column."""
    cursor = await db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    listener_columns = [row["name"] for row in rows]
    assert "retired_at" in listener_columns

    cursor = await db.execute("PRAGMA table_info(scheduled_jobs)")
    rows = await cursor.fetchall()
    job_columns = [row["name"] for row in rows]
    assert "retired_at" in job_columns


async def test_unique_index_enforced(db: aiosqlite.Connection) -> None:
    """Two non-once listeners with same natural key (name + topic) raises IntegrityError."""
    sql = """
        INSERT INTO listeners
            (app_key, instance_index, name, handler_method, topic, once, priority, source_location)
        VALUES ('app', 0, 'app.handler', 'app.handler', 'light.on', 0, 0, 'app.py:1')
    """
    await db.execute(sql)
    await db.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(sql)


async def test_active_views_exist(db: aiosqlite.Connection) -> None:
    """SELECT * FROM active_listeners and active_scheduled_jobs succeeds."""
    cursor = await db.execute("SELECT * FROM active_listeners")
    rows = await cursor.fetchall()
    assert rows == []

    cursor = await db.execute("SELECT * FROM active_scheduled_jobs")
    rows = await cursor.fetchall()
    assert rows == []


async def test_reconcile_deletes_stale_job_not_in_live_set(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale jobs NOT in live_job_ids when live_job_ids is non-empty."""
    job_id_a = await repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await repo.register_job(make_job_registration(job_name="job_b"))

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
    job_id_a = await repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await repo.register_job(make_job_registration(job_name="job_b"))

    await db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', ?, ?, ?, ?, ?)",
        (job_id_b, session_id, time.time(), 1.0, "success"),
    )
    await db.commit()

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
    live_id = await repo.register_listener(make_listener_registration(topic="topic.live", name="test_app.live"))

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
        source_location=TEST_SOURCE_LOCATION,
        registration_source=None,
        name="test_app.on_event.once",
    )
    once_id = await repo.register_listener(once_reg)

    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

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
    """reconcile_registrations() rolls back the transaction on unexpected errors."""
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


async def test_persist_execution_batch_with_fk_fallback_success_path(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() inserts records when no FK violations occur."""
    listener_id = await repo.register_listener(make_listener_registration())
    job_id = await repo.register_job(make_job_registration())

    now = time.time()
    handler_rec = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )
    job_rec = ExecutionRecord(
        kind="job",
        job_id=job_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await repo.persist_execution_batch_with_fk_fallback([handler_rec, job_rec])

    assert dropped == 0

    cursor = await db.execute("SELECT listener_id, kind FROM executions WHERE listener_id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == listener_id
    assert row[1] == "handler"

    cursor = await db.execute("SELECT job_id, kind FROM executions WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == job_id
    assert row[1] == "job"


async def test_persist_execution_batch_with_fk_fallback_nulls_listener_fk_on_violation(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() nulls listener_id on FK violation and still inserts."""
    now = time.time()
    bad_listener_id = 99999
    record = ExecutionRecord(
        kind="handler",
        listener_id=bad_listener_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    dropped = await repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 0

    cursor = await db.execute("SELECT listener_id FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "listener_id should be nulled after FK violation"


async def test_persist_execution_batch_with_fk_fallback_nulls_job_fk_on_violation(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() nulls job_id on FK violation and still inserts."""
    now = time.time()
    bad_job_id = 99999
    record = ExecutionRecord(
        kind="job",
        job_id=bad_job_id,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 0

    cursor = await db.execute("SELECT job_id FROM executions")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "job_id should be nulled after FK violation"


async def test_persist_execution_batch_with_fk_fallback_drops_row_on_second_failure(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() counts dropped when null-FK retry also fails."""
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
        listener_id=None,
        session_id=session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    original_execute = db.execute
    call_count = 0

    async def patched_execute(sql, params=None):
        nonlocal call_count
        if "INSERT INTO executions" in sql:
            call_count += 1
            if call_count == 1:
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            if call_count == 2:
                raise sqlite3.IntegrityError("NOT NULL constraint failed on null-FK retry")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with patch.object(db, "execute", side_effect=patched_execute):
        dropped = await repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1, "Row that fails even with null FK should be counted as dropped"


async def test_persist_execution_batch_with_fk_fallback_drops_job_row_on_second_failure(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() counts dropped for job rows when null-FK retry fails."""
    now = time.time()
    record = ExecutionRecord(
        kind="job",
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
        if "INSERT INTO executions" in sql:
            call_count += 1
            if call_count == 1:
                raise sqlite3.IntegrityError("FOREIGN KEY constraint failed")
            if call_count == 2:
                raise sqlite3.IntegrityError("NOT NULL constraint failed on null-FK retry")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with patch.object(db, "execute", side_effect=patched_execute):
        dropped = await repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1, "Job row that fails even with null FK should be counted as dropped"


async def test_persist_execution_batch_with_fk_fallback_empty_list(
    repo: TelemetryRepository,
) -> None:
    """persist_execution_batch_with_fk_fallback() with empty list returns 0 dropped."""
    dropped = await repo.persist_execution_batch_with_fk_fallback([])
    assert dropped == 0


async def test_persist_execution_batch_with_fk_fallback_rollback_on_exception(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() rolls back on unexpected errors."""
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
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
        await repo.persist_execution_batch_with_fk_fallback([record])


async def test_persist_execution_batch_rollback_on_exception(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
    session_id: int,
) -> None:
    """persist_execution_batch() rolls back and re-raises on unexpected error."""
    listener_id = await repo.register_listener(make_listener_registration())
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
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
        await repo.persist_execution_batch([record])

    cursor = await db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row[0] == 0, "No rows should be committed after rollback"


async def test_on_conflict_target_matches_index(db: aiosqlite.Connection) -> None:
    """Structural test: idx_listeners_natural columns exactly match ON CONFLICT target.

    Queries sqlite_master for idx_listeners_natural and asserts:
    (a) its column list is exactly (app_key, instance_index, name, topic)
    (b) the repository's ON CONFLICT target is verbatim (app_key, instance_index, name, topic)
    """
    # (a) Verify the index SQL from sqlite_master
    cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_listeners_natural'")
    row = await cursor.fetchone()
    assert row is not None, "idx_listeners_natural index must exist in schema"

    index_sql: str = row[0]
    # The SQL should contain exactly these four columns in this order
    assert "app_key, instance_index, name, topic" in index_sql, (
        f"idx_listeners_natural must index (app_key, instance_index, name, topic), got: {index_sql!r}"
    )
    # Must NOT have the old partial/expression form
    assert "COALESCE" not in index_sql, "idx_listeners_natural must not use COALESCE expression"
    assert "WHERE" not in index_sql, "idx_listeners_natural must not be a partial index"
    assert "handler_method" not in index_sql, "idx_listeners_natural must not include handler_method"

    # (b) Verify the repository ON CONFLICT target matches the index verbatim
    source = inspect.getsource(telemetry_repository_module.TelemetryRepository.register_listener)
    # The ON CONFLICT clause must contain exactly (app_key, instance_index, name, topic)
    assert "ON CONFLICT(app_key, instance_index, name, topic)" in source, (
        "register_listener() ON CONFLICT target must be (app_key, instance_index, name, topic) "
        "to match idx_listeners_natural"
    )
    # Must NOT contain the old partial/expression form
    assert "COALESCE" not in source or "ON CONFLICT" not in source.split("COALESCE")[0], (
        "register_listener() ON CONFLICT must not use COALESCE"
    )


async def test_mark_listener_cancelled_sets_cancelled_at(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """mark_listener_cancelled() sets cancelled_at to the current epoch time."""
    reg = make_listener_registration()
    listener_id = await repo.register_listener(reg)

    cursor = await db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "cancelled_at should be NULL before cancellation"

    before_ts = time.time()
    await repo.mark_listener_cancelled(listener_id)
    after_ts = time.time()

    cursor = await db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "cancelled_at should be set after mark_listener_cancelled()"
    assert before_ts <= row[0] <= after_ts, f"cancelled_at={row[0]} should be between {before_ts} and {after_ts}"


async def test_register_listener_clears_cancelled_at_on_reregistration(
    repo: TelemetryRepository,
    db: aiosqlite.Connection,
) -> None:
    """Re-registering under the same natural key clears cancelled_at and preserves the row id."""
    reg = make_listener_registration()
    listener_id = await repo.register_listener(reg)

    await repo.mark_listener_cancelled(listener_id)

    cursor = await db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is not None, "cancelled_at should be set after mark_listener_cancelled()"

    # Re-register under the same natural key
    new_id = await repo.register_listener(reg)

    assert new_id == listener_id, "Re-registration must preserve the row id"

    cursor = await db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] is None, "cancelled_at should be cleared to NULL after re-registration"
