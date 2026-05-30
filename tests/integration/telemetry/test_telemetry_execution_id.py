"""Integration tests for execution_id, trigger_context_id, trigger_origin persist/query roundtrip.

Covers the new columns added to the unified executions table (001.sql).
"""

import time

import pytest

from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.core.database_service import DatabaseService
from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.core.telemetry_repository import TelemetryRepository, _execution_insert_params
from hassette.scheduler.classes import JobExecutionRecord

from .helpers import (
    insert_job,
    insert_listener,
)


@pytest.fixture
def repo(db: tuple[DatabaseService, int]) -> TelemetryRepository:
    db_service, _ = db
    return TelemetryRepository(db_service)


def make_inv_record(
    listener_id: int | None,
    session_id: int,
    *,
    execution_id: str | None = None,
    trigger_context_id: str | None = None,
    trigger_origin: str | None = None,
) -> HandlerInvocationRecord:
    return HandlerInvocationRecord(
        listener_id=listener_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=10.0,
        status="success",
        execution_id=execution_id,
        trigger_context_id=trigger_context_id,
        trigger_origin=trigger_origin,
    )


def make_job_record(
    job_id: int | None,
    session_id: int,
    *,
    execution_id: str | None = None,
) -> JobExecutionRecord:
    return JobExecutionRecord(
        job_id=job_id,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=20.0,
        status="success",
        execution_id=execution_id,
    )


class TestHandlerInvocationExecutionId:
    async def test_persist_and_query_handler_invocation_with_execution_id(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a HandlerInvocationRecord with all three new fields and query them back."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(
            listener_id,
            session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="LOCAL",
        )

        await repo.persist_batch([record], [])

        results = await query_service.get_handler_invocations(listener_id, limit=10)
        assert len(results) == 1
        inv = results[0]
        assert inv.execution_id == "abc-123"
        assert inv.trigger_context_id == "ctx-456"
        assert inv.trigger_origin == "LOCAL"

    async def test_null_execution_id_persists_and_queries(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a record with execution_id=None and confirm it comes back as None (not empty string)."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(listener_id, session_id, execution_id=None)

        await repo.persist_batch([record], [])

        results = await query_service.get_handler_invocations(listener_id, limit=10)
        assert len(results) == 1
        assert results[0].execution_id is None

    async def test_fk_fallback_drops_handler_row_on_stale_listener_fk(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository
    ) -> None:
        """A stale listener_id FK drops the execution row — orphan null-FK rows are impossible.

        The unified ``executions`` CHECK constraint ``(listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1``
        forbids a handler row with a null listener_id. The FK fallback nulls listener_id on the FK
        violation, which then fails the CHECK, so the row is dropped rather than orphaned. Under
        synchronous registration a listener is always persisted before it is routable, so this path
        does not occur in practice — but the repository must drop rather than corrupt on a stale FK.
        """
        db_svc, _session_id = db
        nonexistent_listener_id = 99999
        record = make_inv_record(
            nonexistent_listener_id,
            _session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="REMOTE",
        )

        dropped = await repo.persist_batch_with_fk_fallback([record], [])
        assert dropped == 1  # CHECK prevents a null-FK orphan; the row is dropped

        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 0  # no orphan row written

    async def test_shared_params_match_persist_batch_columns(self, db: tuple[DatabaseService, int]) -> None:
        """_execution_insert_params() keys must match the executions table columns used in persist_batch()."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = ExecutionRecord(
            kind="handler",
            listener_id=listener_id,
            session_id=session_id,
            execution_start_ts=time.time(),
            duration_ms=10.0,
            status="success",
            execution_id="abc-test",
            trigger_context_id="ctx-test",
            trigger_origin="LOCAL",
        )
        params = _execution_insert_params(record)

        # Verify params has all expected keys
        assert "kind" in params
        assert "execution_id" in params
        assert "trigger_context_id" in params
        assert "trigger_origin" in params
        assert "listener_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build actual column list from keys — same as persist_execution_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        # Verify the constructed INSERT works against a real DB
        await db_svc.db.execute(
            f"INSERT INTO executions ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        # Count rows — should have exactly 1
        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1


class TestJobExecutionExecutionId:
    async def test_persist_and_query_job_execution_with_execution_id(
        self, db: tuple[DatabaseService, int], repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a JobExecutionRecord with execution_id and query it back."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)
        record = make_job_record(job_id, session_id, execution_id="def-789")

        await repo.persist_batch([], [record])

        results = await query_service.get_job_executions(job_id, limit=10)
        assert len(results) == 1
        je = results[0]
        assert je.execution_id == "def-789"
        assert not hasattr(je, "trigger_context_id"), "JobExecution must not have trigger_context_id"

    async def test_job_shared_params_match_persist_batch_columns(self, db: tuple[DatabaseService, int]) -> None:
        """_execution_insert_params() keys for kind=job must match the executions table columns."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)
        record = ExecutionRecord(
            kind="job",
            job_id=job_id,
            session_id=session_id,
            execution_start_ts=time.time(),
            duration_ms=20.0,
            status="success",
            execution_id="def-test",
        )
        params = _execution_insert_params(record)

        # Verify params has all expected keys
        assert "kind" in params
        assert "execution_id" in params
        assert "job_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build actual column list from keys — same as persist_execution_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        # Verify the constructed INSERT works against a real DB
        await db_svc.db.execute(
            f"INSERT INTO executions ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        # Count rows — should have exactly 1
        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1
