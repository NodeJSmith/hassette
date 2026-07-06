"""Unit tests for TelemetryRepository — error handling, FK fallback, rollback, and structural checks."""

import inspect
import sqlite3
import time
from unittest.mock import patch

import aiosqlite
import pytest

import hassette.core.telemetry.repository as telemetry_repository_module
from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.repository import TelemetryRepository
from hassette.test_utils.factories import make_job_registration, make_listener_registration


async def test_reconcile_rollback_on_exception(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
) -> None:
    """reconcile_registrations() rolls back the transaction on unexpected errors."""
    original_execute = telemetry_db.execute
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
        patch.object(telemetry_db, "execute", side_effect=failing_execute),
        pytest.raises(RuntimeError, match="simulated DB error"),
    ):
        await telemetry_repo.reconcile_registrations("test_app", [], [])


async def test_persist_execution_batch_with_fk_fallback_success_path(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() inserts records when no FK violations occur."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    job_id = await telemetry_repo.register_job(make_job_registration())

    now = time.time()
    handler_rec = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )
    job_rec = ExecutionRecord(
        kind="job",
        job_id=job_id,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([handler_rec, job_rec])

    assert dropped == 0

    cursor = await telemetry_db.execute(
        "SELECT listener_id, kind FROM executions WHERE listener_id = ?", (listener_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == listener_id
    assert row[1] == "handler"

    cursor = await telemetry_db.execute("SELECT job_id, kind FROM executions WHERE job_id = ?", (job_id,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == job_id
    assert row[1] == "job"


async def test_persist_execution_batch_with_fk_fallback_drops_on_listener_fk_violation(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() drops handler record with bad listener_id.

    The null-FK retry also fails because the CHECK constraint requires exactly one
    of listener_id or job_id to be non-null.
    """
    now = time.time()
    bad_listener_id = 99999
    record = ExecutionRecord(
        kind="handler",
        listener_id=bad_listener_id,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1

    cursor = await telemetry_db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row[0] == 0, "Row should be dropped — null FK violates CHECK constraint"


async def test_persist_execution_batch_with_fk_fallback_drops_on_job_fk_violation(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() drops job record with bad job_id.

    The null-FK retry also fails because the CHECK constraint requires exactly one
    of listener_id or job_id to be non-null.
    """
    now = time.time()
    bad_job_id = 99999
    record = ExecutionRecord(
        kind="job",
        job_id=bad_job_id,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1

    cursor = await telemetry_db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row[0] == 0, "Row should be dropped — null FK violates CHECK constraint"


async def test_persist_execution_batch_with_fk_fallback_drops_row_on_second_failure(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() counts dropped when null-FK retry also fails."""
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
        listener_id=None,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    original_execute = telemetry_db.execute
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

    with patch.object(telemetry_db, "execute", side_effect=patched_execute):
        dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1, "Row that fails even with null FK should be counted as dropped"


async def test_persist_execution_batch_with_fk_fallback_drops_job_row_on_second_failure(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() counts dropped for job rows when null-FK retry fails."""
    now = time.time()
    record = ExecutionRecord(
        kind="job",
        job_id=None,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=10.0,
        status="success",
    )

    original_execute = telemetry_db.execute
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

    with patch.object(telemetry_db, "execute", side_effect=patched_execute):
        dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([record])

    assert dropped == 1, "Job row that fails even with null FK should be counted as dropped"


async def test_persist_execution_batch_with_fk_fallback_empty_list(
    telemetry_repo: TelemetryRepository,
) -> None:
    """persist_execution_batch_with_fk_fallback() with empty list returns 0 dropped."""
    dropped = await telemetry_repo.persist_execution_batch_with_fk_fallback([])
    assert dropped == 0


async def test_persist_execution_batch_with_fk_fallback_rollback_on_exception(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch_with_fk_fallback() rolls back on unexpected errors."""
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
        listener_id=None,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    original_execute = telemetry_db.execute

    async def patched_execute(sql, params=None):
        if "BEGIN" in sql:
            raise RuntimeError("simulated connection failure")
        if params is not None:
            return await original_execute(sql, params)
        return await original_execute(sql)

    with (
        patch.object(telemetry_db, "execute", side_effect=patched_execute),
        pytest.raises(RuntimeError, match="simulated connection failure"),
    ):
        await telemetry_repo.persist_execution_batch_with_fk_fallback([record])


async def test_persist_execution_batch_rollback_on_exception(
    telemetry_repo: TelemetryRepository,
    telemetry_db: aiosqlite.Connection,
    telemetry_session_id: int,
) -> None:
    """persist_execution_batch() rolls back and re-raises on unexpected error."""
    listener_id = await telemetry_repo.register_listener(make_listener_registration())
    now = time.time()
    record = ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        session_id=telemetry_session_id,
        execution_start_ts=now,
        duration_ms=5.0,
        status="success",
    )

    async def failing_executemany(_sql, _params):
        raise RuntimeError("simulated executemany failure")

    with (
        patch.object(telemetry_db, "executemany", side_effect=failing_executemany),
        pytest.raises(RuntimeError, match="simulated executemany failure"),
    ):
        await telemetry_repo.persist_execution_batch([record])

    cursor = await telemetry_db.execute("SELECT COUNT(*) FROM executions")
    row = await cursor.fetchone()
    assert row[0] == 0, "No rows should be committed after rollback"


async def test_on_conflict_target_matches_index(telemetry_db: aiosqlite.Connection) -> None:
    """Structural test: idx_listeners_natural columns exactly match ON CONFLICT target.

    Queries sqlite_master for idx_listeners_natural and asserts:
    (a) its column list is exactly (app_key, instance_index, name, topic)
    (b) the repository's ON CONFLICT target is verbatim (app_key, instance_index, name, topic)
    """
    # (a) Verify the index SQL from sqlite_master
    cursor = await telemetry_db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_listeners_natural'"
    )
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
