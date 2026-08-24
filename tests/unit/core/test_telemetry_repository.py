"""Unit tests for TelemetryRepository — registration, reconciliation, upsert, and execution batch."""

import time
from typing import Any

import aiosqlite
import pytest

from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.repository import (
    TelemetryRepository,
    _build_delete_query,
    _build_retire_query,
)
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY
from hassette.test_utils.factories import (
    make_execution_record,
    make_job_registration,
    make_listener_registration,
)
from hassette.test_utils.sql_helpers import insert_execution_row

ONCE_LISTENER_NAME = "test_app.on_event.once"


async def assert_listener_count(db: aiosqlite.Connection, listener_id: int, expected: int, message: str) -> None:
    """Assert the number of listener rows with the given id matches expected."""
    cursor = await db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row["count"] == expected, message


async def fetch_listener_field(db: aiosqlite.Connection, listener_id: int, field: str) -> Any:
    """Return a single column value from the listeners row with the given id."""
    cursor = await db.execute(f"SELECT {field} FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    return row[field]


async def insert_committed_execution(db: aiosqlite.Connection, session_id: int, **kwargs: Any) -> None:
    """Insert an execution row (1ms duration, current timestamp) and commit it."""
    await insert_execution_row(db, session_id=session_id, execution_start_ts=time.time(), duration_ms=1.0, **kwargs)
    await db.commit()


async def insert_new_session(db: aiosqlite.Connection) -> int:
    """Insert a second 'running' session row and return its id.

    Simulates reconciliation running against a session distinct from the fixture-provided
    ``telemetry_session_id`` — used by tests that verify once=True cleanup against a newer
    session.
    """
    now = time.time()
    cursor = await db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None
    return new_session_id


async def test_register_listener_inserts_and_returns_id(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_listener() inserts a row and returns a valid positive integer ID."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    assert isinstance(listener_id, int)
    assert listener_id > 0

    cursor = await telemetry_db.execute("SELECT id, app_key, topic FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == DEFAULT_TEST_APP_KEY
    assert row["topic"] == "hass.event.state_changed"


async def test_register_job_inserts_and_returns_id(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() inserts a row and returns a valid positive integer ID."""
    reg = make_job_registration()
    job_id = await telemetry_repo.register_job(reg)

    assert isinstance(job_id, int)
    assert job_id > 0

    cursor = await telemetry_db.execute("SELECT id, app_key, job_name FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["app_key"] == DEFAULT_TEST_APP_KEY
    assert row["job_name"] == "test_job"


async def test_register_job_persists_group(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() writes the group value to the database."""
    reg = make_job_registration(job_name="morning_job", group="morning")
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["group"] == "morning", f"Expected group='morning', got {row['group']!r}"


async def test_register_job_persists_null_group(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() persists NULL for group when group is not set."""
    reg = make_job_registration()
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute('SELECT "group" FROM scheduled_jobs WHERE id = ?', (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["group"] is None, f"Expected group=None, got {row['group']!r}"


async def test_mark_job_removed_sets_removed_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_job_removed() sets removed_at to the current epoch time."""
    reg = make_job_registration(job_name="removable_job")
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute("SELECT removed_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is None, "removed_at should be NULL before removal"

    before_ts = time.time()
    await telemetry_repo.mark_job_removed(job_id)
    after_ts = time.time()

    cursor = await telemetry_db.execute("SELECT removed_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is not None, "removed_at should be set after mark_job_removed()"
    assert before_ts <= row["removed_at"] <= after_ts, (
        f"removed_at={row['removed_at']} should be between {before_ts} and {after_ts}"
    )


async def test_mark_job_status_updates_status_and_reason(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_job_status() writes schedule_status and schedule_status_reason to the row."""
    reg = make_job_registration(job_name="status_job")
    job_id = await telemetry_repo.register_job(reg)

    await telemetry_repo.mark_job_status(job_id, "waiting", None)

    cursor = await telemetry_db.execute(
        "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["schedule_status"] == "waiting"
    assert row["schedule_status_reason"] is None

    await telemetry_repo.mark_job_status(job_id, "completed", "trigger_error")

    cursor = await telemetry_db.execute(
        "SELECT schedule_status, schedule_status_reason FROM scheduled_jobs WHERE id = ?", (job_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["schedule_status"] == "completed"
    assert row["schedule_status_reason"] == "trigger_error", (
        f"Expected schedule_status_reason='trigger_error', got {row['schedule_status_reason']!r}"
    )


async def test_reconcile_deletes_stale_without_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale non-once listeners with no execution history."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    await assert_listener_count(telemetry_db, listener_id, 0, "Stale listener without history should be deleted")

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale job without history should be deleted"


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_reconcile_retires_stale_with_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() sets retired_at on stale rows that have execution history."""
    # dup-ignore-end
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    # Create history in the unified executions table
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=listener_id)
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="job", job_id=job_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    retired_at = await fetch_listener_field(telemetry_db, listener_id, "retired_at")
    assert retired_at is not None, "Stale listener with history should have retired_at set"

    cursor = await telemetry_db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is not None, "Stale job with history should have retired_at set"


async def test_reconcile_preserves_live_listeners(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() preserves listeners whose IDs are in the live set."""
    reg_a = make_listener_registration(topic="topic.a", name="test_app.on_event_a")
    reg_b = make_listener_registration(topic="topic.b", name="test_app.on_event_b")
    id_a = await telemetry_repo.register_listener(reg_a)
    id_b = await telemetry_repo.register_listener(reg_b)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [id_a], [])

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (id_a,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "Live listener should be preserved"

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (id_b,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale listener without history should be deleted"


@pytest.mark.usefixtures("telemetry_session_id")
async def test_reconcile_deletes_once_true_previous_session(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True rows from previous sessions (no current executions)."""
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=new_session_id)

    await assert_listener_count(telemetry_db, once_id, 0, "once=True listener from previous session should be deleted")


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_reconcile_preserves_once_true_with_current_executions(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() preserves once=True rows that have current-session executions."""
    # dup-ignore-end
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    # Create an execution in the CURRENT session
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=once_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=telemetry_session_id)

    await assert_listener_count(
        telemetry_db, once_id, 1, "once=True listener with current-session executions should be preserved"
    )


async def test_reconcile_empty_ids_no_crash(
    telemetry_repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_reconcile_resets_retired_at_on_reupsert(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """After a row is retired, re-upserting it (same natural key) resets retired_at to NULL."""
    # dup-ignore-end
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    # Create history so reconciliation retires rather than deletes
    await insert_committed_execution(telemetry_db, telemetry_session_id, kind="handler", listener_id=listener_id)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    retired_at = await fetch_listener_field(telemetry_db, listener_id, "retired_at")
    assert retired_at is not None, "Row should be retired after reconciliation"

    new_id = await telemetry_repo.register_listener(reg)
    assert new_id == listener_id, "Re-upsert should return the same ID"

    cursor = await telemetry_db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is None, "retired_at should be reset to NULL after re-upsert"


async def test_upsert_same_natural_key_returns_same_id(
    telemetry_repo: TelemetryRepository,
) -> None:
    """register_listener() with same natural key returns the same ID (upsert)."""
    reg = make_listener_registration()
    id_a = await telemetry_repo.register_listener(reg)
    id_b = await telemetry_repo.register_listener(reg)
    assert id_a == id_b


async def test_upsert_different_natural_key_returns_new_id(
    telemetry_repo: TelemetryRepository,
) -> None:
    """register_listener() with different topic returns a new ID."""
    id_a = await telemetry_repo.register_listener(make_listener_registration(topic="topic.a", name="test_app.on_a"))
    id_b = await telemetry_repo.register_listener(make_listener_registration(topic="topic.b", name="test_app.on_b"))
    assert id_a != id_b


async def test_upsert_updates_mutable_fields(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """Upsert updates debounce (mutable field) on conflict."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    updated_reg = make_listener_registration(debounce=5.0)
    new_id = await telemetry_repo.register_listener(updated_reg)
    assert new_id == listener_id

    cursor = await telemetry_db.execute("SELECT debounce FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["debounce"] == 5.0


async def test_once_true_upserts_by_name_topic(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """once=True listeners with a name upsert on (name, topic) like once=False listeners."""
    # Two registrations with same name+topic — should upsert to same row
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    id_a = await telemetry_repo.register_listener(once_reg)
    id_b = await telemetry_repo.register_listener(once_reg)
    assert id_a == id_b

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE name = ?", (ONCE_LISTENER_NAME,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "Upsert should produce a single row, not two inserts"


async def test_upsert_does_not_update_human_description(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """human_description is NOT updated on upsert (not in the DO UPDATE SET list)."""
    reg = make_listener_registration(human_description="entity light.kitchen")
    listener_id = await telemetry_repo.register_listener(reg)

    reg2 = make_listener_registration(human_description="entity light.kitchen")
    new_id = await telemetry_repo.register_listener(reg2)
    assert new_id == listener_id

    cursor = await telemetry_db.execute("SELECT human_description FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["human_description"] == "entity light.kitchen"


async def test_upsert_with_name_overrides_key(
    telemetry_repo: TelemetryRepository,
) -> None:
    """Two listeners with same handler+topic but different name= get different IDs."""
    reg_a = make_listener_registration(name="listener_a")
    reg_b = make_listener_registration(name="listener_b")
    id_a = await telemetry_repo.register_listener(reg_a)
    id_b = await telemetry_repo.register_listener(reg_b)
    assert id_a != id_b


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_persist_execution_batch_inserts_handler_records(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts handler ExecutionRecords into the executions table."""
    # dup-ignore-end
    listener_id = await telemetry_repo.register_listener(make_listener_registration())

    now = time.time()
    records = [
        make_execution_record(listener_id=listener_id, session_id=telemetry_session_id, execution_start_ts=now),
        ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=telemetry_session_id,
            execution_start_ts=now + 1,
            duration_ms=10.0,
            status="error",
            error_type="ValueError",
            error_message="oops",
            error_traceback="Traceback...",
        ),
    ]

    await telemetry_repo.persist_execution_batch(records)

    cursor = await telemetry_db.execute(
        "SELECT status, duration_ms, kind FROM executions WHERE listener_id = ? ORDER BY execution_start_ts",
        (listener_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["status"] == "success"
    assert rows[0]["kind"] == "handler"
    assert rows[1]["status"] == "error"
    assert rows[1]["kind"] == "handler"


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_persist_execution_batch_inserts_job_records(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts job ExecutionRecords into the executions table."""
    # dup-ignore-end
    job_id = await telemetry_repo.register_job(make_job_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="job",
            job_id=job_id,
            session_id=telemetry_session_id,
            execution_start_ts=now,
            duration_ms=20.0,
            status="success",
        ),
    ]

    await telemetry_repo.persist_execution_batch(records)

    # dup-ignore-start: shares the "fetch one row, assert count then fields" shape with
    # tests/integration/test_command_executor.py's post-drain assertions — different test tier
    # (unit vs. integration) exercising unrelated code paths (TelemetryRepository.persist_execution_batch
    # here vs. CommandExecutor.drain_and_persist there); not extractable across that boundary.
    cursor = await telemetry_db.execute(
        "SELECT status, job_id, kind FROM executions WHERE job_id = ?",
        (job_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["job_id"] == job_id
    assert rows[0]["kind"] == "job"
    # dup-ignore-end


async def test_persist_execution_batch_handles_empty_list(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """persist_execution_batch() with empty list completes without error and inserts nothing."""
    await telemetry_repo.persist_execution_batch([])

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM executions")
    row = await cursor.fetchone()
    assert row["count"] == 0


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_persist_execution_batch_unified(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts ExecutionRecord rows into executions with correct kind."""
    # dup-ignore-end
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    now = time.time()
    records = [
        make_execution_record(listener_id=listener_id, session_id=telemetry_session_id, execution_start_ts=now),
        ExecutionRecord(
            kind="job",
            job_id=job_id,
            session_id=telemetry_session_id,
            execution_start_ts=now + 1,
            duration_ms=15.0,
            status="success",
        ),
    ]

    await telemetry_repo.persist_execution_batch(records)

    cursor = await telemetry_db.execute("SELECT kind, listener_id, job_id FROM executions ORDER BY execution_start_ts")
    rows = await cursor.fetchall()
    assert len(rows) == 2
    assert rows[0]["kind"] == "handler"
    assert rows[0]["listener_id"] == listener_id
    assert rows[0]["job_id"] is None
    assert rows[1]["kind"] == "job"
    assert rows[1]["job_id"] == job_id
    assert rows[1]["listener_id"] is None


async def test_schema_has_name_column(telemetry_db: aiosqlite.Connection) -> None:
    """Listeners table includes the name column (NOT NULL in unified schema)."""
    cursor = await telemetry_db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    column_names = [row["name"] for row in rows]
    assert "name" in column_names


async def test_schema_has_retired_at_column(telemetry_db: aiosqlite.Connection) -> None:
    """Both listeners and scheduled_jobs have a retired_at column."""
    cursor = await telemetry_db.execute("PRAGMA table_info(listeners)")
    rows = await cursor.fetchall()
    listener_columns = [row["name"] for row in rows]
    assert "retired_at" in listener_columns

    cursor = await telemetry_db.execute("PRAGMA table_info(scheduled_jobs)")
    rows = await cursor.fetchall()
    job_columns = [row["name"] for row in rows]
    assert "retired_at" in job_columns


async def test_unique_index_enforced(telemetry_db: aiosqlite.Connection) -> None:
    """Two non-once listeners with same natural key (name + topic) raises IntegrityError."""
    sql = """
        INSERT INTO listeners
            (app_key, instance_index, name, handler_method, topic, once, priority, source_location)
        VALUES ('app', 0, 'app.handler', 'app.handler', 'light.on', 0, 0, 'app.py:1')
    """
    await telemetry_db.execute(sql)
    await telemetry_db.commit()

    with pytest.raises(aiosqlite.IntegrityError):
        await telemetry_db.execute(sql)


async def test_active_views_exist(telemetry_db: aiosqlite.Connection) -> None:
    """SELECT * FROM active_listeners and active_scheduled_jobs succeeds."""
    cursor = await telemetry_db.execute("SELECT * FROM active_listeners")
    rows = await cursor.fetchall()
    assert rows == []

    cursor = await telemetry_db.execute("SELECT * FROM active_scheduled_jobs")
    rows = await cursor.fetchall()
    assert rows == []


async def test_reconcile_deletes_stale_job_not_in_live_set(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale jobs NOT in live_job_ids when live_job_ids is non-empty."""
    job_id_a = await telemetry_repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await telemetry_repo.register_job(make_job_registration(job_name="job_b"))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [job_id_a])

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (job_id_a,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "Live job should be preserved"

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (job_id_b,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale job without history should be deleted (non-empty live_job_ids branch)"


# dup-ignore-start: pytest test function signature — each test independently declares the
# telemetry_repo/telemetry_db/telemetry_session_id fixtures it needs; Python has no way to share a
# function signature between separate test functions, and bundling these three fixtures into one
# object would require a new tests/unit/core/conftest.py fixture, out of scope for this cluster
# (see design/specs/099-dedupe-tests-unit-core/design.md — no new conftest.py helpers per task).
async def test_reconcile_retires_stale_job_with_history_non_empty_live_set(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() retires stale jobs with history when live_job_ids is non-empty."""
    # dup-ignore-end
    job_id_a = await telemetry_repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await telemetry_repo.register_job(make_job_registration(job_name="job_b"))

    await insert_execution_row(
        telemetry_db,
        kind="job",
        job_id=job_id_b,
        session_id=telemetry_session_id,
        execution_start_ts=time.time(),
        duration_ms=1.0,
    )
    await telemetry_db.commit()

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [job_id_a])

    cursor = await telemetry_db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id_b,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is not None, (
        "Stale job with history should have retired_at set (non-empty live_job_ids branch)"
    )

    cursor = await telemetry_db.execute("SELECT retired_at FROM scheduled_jobs WHERE id = ?", (job_id_a,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is None, "Live job should not be retired"


async def test_reconcile_once_true_delete_non_empty_live_listener_ids(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes once=True listeners not in live IDs when live_listener_ids is non-empty."""
    live_reg = make_listener_registration(topic="topic.live", name="test_app.live")
    live_id = await telemetry_repo.register_listener(live_reg)

    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [live_id], [], session_id=new_session_id)

    await assert_listener_count(
        telemetry_db,
        once_id,
        0,
        "once=True listener from previous session should be deleted (non-empty live_listener_ids branch)",
    )

    await assert_listener_count(telemetry_db, live_id, 1, "Live listener should be preserved")


async def test_mark_listener_cancelled_sets_removed_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_listener_cancelled() sets removed_at to the current epoch time."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is None, "removed_at should be NULL before removal"

    before_ts = time.time()
    await telemetry_repo.mark_listener_cancelled(listener_id)
    after_ts = time.time()

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is not None, "removed_at should be set after mark_listener_cancelled()"
    assert before_ts <= removed_at <= after_ts


async def test_register_listener_clears_removed_at_on_reregistration(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """Re-registering under the same natural key clears removed_at and preserves the row id."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    await telemetry_repo.mark_listener_cancelled(listener_id)

    removed_at = await fetch_listener_field(telemetry_db, listener_id, "removed_at")
    assert removed_at is not None, "removed_at should be set after mark_listener_cancelled()"

    new_id = await telemetry_repo.register_listener(reg)
    assert new_id == listener_id, "Re-registration must preserve the row id"

    cursor = await telemetry_db.execute("SELECT removed_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["removed_at"] is None, "removed_at should be cleared to NULL after re-registration"


@pytest.mark.parametrize(("table", "history_fk"), [("listeners", "listener_id"), ("scheduled_jobs", "job_id")])
def test_build_delete_query_includes_instance_index_clause(table: str, history_fk: str) -> None:
    """_build_delete_query() with instance_index adds the AND instance_index clause and bind param."""
    sql, params = _build_delete_query(table, DEFAULT_TEST_APP_KEY, [], history_fk, instance_index=2)

    assert "AND instance_index = :instance_index" in sql
    assert params["instance_index"] == 2


@pytest.mark.parametrize(("table", "history_fk"), [("listeners", "listener_id"), ("scheduled_jobs", "job_id")])
def test_build_delete_query_omits_instance_index_clause_when_none(table: str, history_fk: str) -> None:
    """_build_delete_query() with instance_index=None (default) adds no clause — backward compatible."""
    sql, params = _build_delete_query(table, DEFAULT_TEST_APP_KEY, [], history_fk)

    assert "instance_index" not in sql
    assert "instance_index" not in params


@pytest.mark.parametrize(("table", "history_fk"), [("listeners", "listener_id"), ("scheduled_jobs", "job_id")])
def test_build_retire_query_includes_instance_index_clause(table: str, history_fk: str) -> None:
    """_build_retire_query() with instance_index adds the AND instance_index clause and bind param."""
    sql, params = _build_retire_query(table, DEFAULT_TEST_APP_KEY, [], history_fk, time.time(), instance_index=3)

    assert "AND instance_index = :instance_index" in sql
    assert params["instance_index"] == 3


@pytest.mark.parametrize(("table", "history_fk"), [("listeners", "listener_id"), ("scheduled_jobs", "job_id")])
def test_build_retire_query_omits_instance_index_clause_when_none(table: str, history_fk: str) -> None:
    """_build_retire_query() with instance_index=None (default) adds no clause — backward compatible."""
    sql, params = _build_retire_query(table, DEFAULT_TEST_APP_KEY, [], history_fk, time.time())

    assert "instance_index" not in sql
    assert "instance_index" not in params


async def test_reconcile_once_true_cleanup_respects_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes the once=True cleanup block.

    Leaves a sibling instance's once=True row untouched. This is the exact regression the
    instance-scoped reconciliation feature exists to prevent — the once=True block bypasses
    the builder functions and must be scoped independently.
    """
    once_reg_0 = make_listener_registration(once=True, name=ONCE_LISTENER_NAME, instance_index=0)
    once_id_0 = await telemetry_repo.register_listener(once_reg_0)

    once_reg_1 = make_listener_registration(once=True, name=ONCE_LISTENER_NAME, instance_index=1)
    once_id_1 = await telemetry_repo.register_listener(once_reg_1)

    new_session_id = await insert_new_session(telemetry_db)

    await telemetry_repo.reconcile_registrations(
        DEFAULT_TEST_APP_KEY, [], [], session_id=new_session_id, instance_index=0
    )

    await assert_listener_count(
        telemetry_db, once_id_0, 0, "once=True listener for the target instance_index should be deleted"
    )
    await assert_listener_count(
        telemetry_db, once_id_1, 1, "once=True listener for the sibling instance_index should be preserved"
    )


async def test_reconcile_scopes_listener_deletion_by_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes non-once listener deletion.

    A stale sibling-instance row (without execution history) is not deleted alongside the
    target instance.
    """
    stale_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=0)
    )
    stale_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=1)
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_index=0)

    await assert_listener_count(
        telemetry_db, stale_instance_0, 0, "Stale listener for the target instance_index should be deleted"
    )
    await assert_listener_count(
        telemetry_db, stale_instance_1, 1, "Sibling instance's listener should be unaffected by scoped reconciliation"
    )


async def test_reconcile_without_instance_index_affects_all_instances(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() without instance_index is unaffected by instance boundaries.

    Matches pre-existing app_key-only-scoped behavior — every instance's stale rows are
    reconciled together.
    """
    listener_instance_0 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=0)
    )
    listener_instance_1 = await telemetry_repo.register_listener(
        make_listener_registration(name="test_app.on_a", instance_index=1)
    )

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    await assert_listener_count(
        telemetry_db, listener_instance_0, 0, "Stale listener for instance_index=0 should be deleted"
    )
    await assert_listener_count(
        telemetry_db, listener_instance_1, 0, "Stale listener for instance_index=1 should also be deleted"
    )


async def test_reconcile_scopes_job_deletion_by_instance_index(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations(instance_index=...) scopes scheduled_jobs deletion.

    A stale sibling-instance job (without execution history) is not deleted alongside the
    target instance — the scheduled_jobs analogue of
    test_reconcile_scopes_listener_deletion_by_instance_index.
    """
    stale_job_instance_0 = await telemetry_repo.register_job(make_job_registration(job_name="job_a", instance_index=0))
    stale_job_instance_1 = await telemetry_repo.register_job(make_job_registration(job_name="job_a", instance_index=1))

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], instance_index=0)

    cursor = await telemetry_db.execute(
        "SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (stale_job_instance_0,)
    )
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale job for the target instance_index should be deleted"

    cursor = await telemetry_db.execute(
        "SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (stale_job_instance_1,)
    )
    row = await cursor.fetchone()
    assert row["count"] == 1, "Sibling instance's job should be unaffected by scoped reconciliation"
