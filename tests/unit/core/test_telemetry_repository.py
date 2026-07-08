"""Unit tests for TelemetryRepository — registration, reconciliation, upsert, and execution batch."""

import time

import aiosqlite
import pytest

from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY
from hassette.test_utils.factories import make_job_registration, make_listener_registration

ONCE_LISTENER_NAME = "test_app.on_event.once"


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


async def test_register_job_persists_name_auto_true(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() writes name_auto=1 when the name was auto-generated."""
    reg = make_job_registration(job_name="run:after:5", name_auto=True)
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute("SELECT name_auto FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["name_auto"] == 1


async def test_register_job_persists_name_auto_false(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """register_job() writes name_auto=0 by default."""
    reg = make_job_registration()
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute("SELECT name_auto FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["name_auto"] == 0


async def test_mark_job_cancelled_sets_cancelled_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_job_cancelled() sets cancelled_at to the current epoch time."""
    reg = make_job_registration(job_name="cancellable_job")
    job_id = await telemetry_repo.register_job(reg)

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is None, "cancelled_at should be NULL before cancellation"

    before_ts = time.time()
    await telemetry_repo.mark_job_cancelled(job_id)
    after_ts = time.time()

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is not None, "cancelled_at should be set after mark_job_cancelled()"
    assert before_ts <= row["cancelled_at"] <= after_ts, (
        f"cancelled_at={row['cancelled_at']} should be between {before_ts} and {after_ts}"
    )


async def test_reconcile_deletes_stale_without_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() deletes stale non-once listeners with no execution history."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale listener without history should be deleted"

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "Stale job without history should be deleted"


async def test_reconcile_retires_stale_with_history(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() sets retired_at on stale rows that have execution history."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    # Create history in the unified executions table
    await telemetry_db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (listener_id, telemetry_session_id, time.time(), 1.0, "success"),
    )
    await telemetry_db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', ?, ?, ?, ?, ?)",
        (job_id, telemetry_session_id, time.time(), 1.0, "success"),
    )
    await telemetry_db.commit()

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    cursor = await telemetry_db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is not None, "Stale listener with history should have retired_at set"

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

    now = time.time()
    cursor = await telemetry_db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await telemetry_db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=new_session_id)

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row["count"] == 0, "once=True listener from previous session should be deleted"


async def test_reconcile_preserves_once_true_with_current_executions(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() preserves once=True rows that have current-session executions."""
    once_reg = make_listener_registration(once=True, name=ONCE_LISTENER_NAME)
    once_id = await telemetry_repo.register_listener(once_reg)

    # Create an execution in the CURRENT session
    await telemetry_db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (once_id, telemetry_session_id, time.time(), 1.0, "success"),
    )
    await telemetry_db.commit()

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [], session_id=telemetry_session_id)

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "once=True listener with current-session executions should be preserved"


async def test_reconcile_empty_ids_no_crash(
    telemetry_repo: TelemetryRepository,
) -> None:
    """reconcile_registrations() with empty live IDs does not crash (no NOT IN () SQL error)."""
    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])


async def test_reconcile_resets_retired_at_on_reupsert(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """After a row is retired, re-upserting it (same natural key) resets retired_at to NULL."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    # Create history so reconciliation retires rather than deletes
    await telemetry_db.execute(
        "INSERT INTO executions (kind, listener_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('handler', ?, ?, ?, ?, ?)",
        (listener_id, telemetry_session_id, time.time(), 1.0, "success"),
    )
    await telemetry_db.commit()

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [], [])

    cursor = await telemetry_db.execute("SELECT retired_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["retired_at"] is not None, "Row should be retired after reconciliation"

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


async def test_persist_execution_batch_inserts_handler_records(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts handler ExecutionRecords into the executions table."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=telemetry_session_id,
            execution_start_ts=now,
            duration_ms=5.0,
            status="success",
        ),
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


async def test_persist_execution_batch_inserts_job_records(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts job ExecutionRecords into the executions table."""
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

    cursor = await telemetry_db.execute(
        "SELECT status, job_id, kind FROM executions WHERE job_id = ?",
        (job_id,),
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "success"
    assert rows[0]["job_id"] == job_id
    assert rows[0]["kind"] == "job"


async def test_persist_execution_batch_handles_empty_list(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """persist_execution_batch() with empty list completes without error and inserts nothing."""
    await telemetry_repo.persist_execution_batch([])

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM executions")
    row = await cursor.fetchone()
    assert row["count"] == 0


async def test_persist_execution_batch_unified(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() inserts ExecutionRecord rows into executions with correct kind."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    now = time.time()
    records = [
        ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=telemetry_session_id,
            execution_start_ts=now,
            duration_ms=5.0,
            status="success",
        ),
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
    """listeners table includes the name column (NOT NULL in unified schema)."""
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


async def test_reconcile_retires_stale_job_with_history_non_empty_live_set(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """reconcile_registrations() retires stale jobs with history when live_job_ids is non-empty."""
    job_id_a = await telemetry_repo.register_job(make_job_registration(job_name="job_a"))
    job_id_b = await telemetry_repo.register_job(make_job_registration(job_name="job_b"))

    await telemetry_db.execute(
        "INSERT INTO executions (kind, job_id, session_id, execution_start_ts, duration_ms, status)"
        " VALUES ('job', ?, ?, ?, ?, ?)",
        (job_id_b, telemetry_session_id, time.time(), 1.0, "success"),
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

    now = time.time()
    cursor = await telemetry_db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (now, now),
    )
    await telemetry_db.commit()
    new_session_id = cursor.lastrowid
    assert new_session_id is not None

    await telemetry_repo.reconcile_registrations(DEFAULT_TEST_APP_KEY, [live_id], [], session_id=new_session_id)

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (once_id,))
    row = await cursor.fetchone()
    assert row["count"] == 0, (
        "once=True listener from previous session should be deleted (non-empty live_listener_ids branch)"
    )

    cursor = await telemetry_db.execute("SELECT COUNT(*) AS count FROM listeners WHERE id = ?", (live_id,))
    row = await cursor.fetchone()
    assert row["count"] == 1, "Live listener should be preserved"


async def test_mark_listener_cancelled_sets_cancelled_at(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """mark_listener_cancelled() sets cancelled_at to the current epoch time."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is None, "cancelled_at should be NULL before cancellation"

    before_ts = time.time()
    await telemetry_repo.mark_listener_cancelled(listener_id)
    after_ts = time.time()

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is not None, "cancelled_at should be set after mark_listener_cancelled()"
    assert before_ts <= row["cancelled_at"] <= after_ts


async def test_register_listener_clears_cancelled_at_on_reregistration(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """Re-registering under the same natural key clears cancelled_at and preserves the row id."""
    reg = make_listener_registration()
    listener_id = await telemetry_repo.register_listener(reg)

    await telemetry_repo.mark_listener_cancelled(listener_id)

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is not None, "cancelled_at should be set after mark_listener_cancelled()"

    new_id = await telemetry_repo.register_listener(reg)
    assert new_id == listener_id, "Re-registration must preserve the row id"

    cursor = await telemetry_db.execute("SELECT cancelled_at FROM listeners WHERE id = ?", (listener_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row["cancelled_at"] is None, "cancelled_at should be cleared to NULL after re-registration"
