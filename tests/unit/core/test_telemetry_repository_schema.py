"""Unit tests for TelemetryRepository execution batch persistence, schema shape, and query builders."""

import time

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
