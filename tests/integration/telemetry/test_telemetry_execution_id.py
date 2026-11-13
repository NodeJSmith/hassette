"""Integration tests for the execution_id and trigger columns' persist/query roundtrip.

Covers execution_id and the trigger columns of the unified executions table (001.sql, 023.sql).
"""

import time

import pytest
from hassette_wire import ExecutionStatus, ExecutionTrigger

from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry.insert_params import execution_insert_params
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.core.telemetry.repository import TelemetryRepository
from tests.support.factories import make_execution_record

from .helpers import (
    DbFixture,
    insert_job,
    insert_listener,
    only_row,
)


@pytest.fixture
def repo(db: DbFixture) -> TelemetryRepository:
    db_service, _ = db
    return TelemetryRepository(db_service)


def make_inv_record(
    listener_id: int | None,
    session_id: int,
    *,
    execution_id: str | None = None,
    trigger_context_id: str | None = None,
    trigger_origin: str | None = None,
) -> ExecutionRecord:
    return ExecutionRecord(
        kind="handler",
        listener_id=listener_id,
        job_id=None,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=10.0,
        status=ExecutionStatus.SUCCESS,
        execution_id=execution_id,
        trigger_context_id=trigger_context_id,
        trigger_origin=trigger_origin,
    )


def make_job_record(job_id: int | None, session_id: int, *, execution_id: str | None = None) -> ExecutionRecord:
    return ExecutionRecord(
        kind="job",
        job_id=job_id,
        listener_id=None,
        session_id=session_id,
        execution_start_ts=time.time(),
        duration_ms=20.0,
        status=ExecutionStatus.SUCCESS,
        execution_id=execution_id,
    )


class TestHandlerInvocationExecutionId:
    async def test_persist_and_query_handler_invocation_with_execution_id(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a handler ExecutionRecord with all three new fields and query them back."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(
            listener_id,
            session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="LOCAL",
        )

        await repo.persist_execution_batch([record])

        inv = await only_row(query_service.get_executions(listener_id=listener_id, kind="handler", limit=10))
        assert inv.execution_id == "abc-123"
        assert inv.trigger is not None
        assert inv.trigger.context_id == "ctx-456"
        assert inv.trigger.origin == "LOCAL"

    async def test_null_execution_id_persists_and_queries(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a record with execution_id=None and confirm it comes back as None (not empty string)."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(listener_id, session_id, execution_id=None)

        await repo.persist_execution_batch([record])

        results = await query_service.get_executions(listener_id=listener_id, kind="handler", limit=10)
        assert len(results) == 1
        assert results[0].execution_id is None

    async def test_fk_fallback_drops_handler_row_on_stale_listener_fk(
        self, db: DbFixture, repo: TelemetryRepository
    ) -> None:
        """A stale listener_id FK drops the execution row — orphan null-FK rows are impossible.

        The unified ``executions`` CHECK constraint ``(listener_id IS NOT NULL) + (job_id IS NOT NULL) = 1``
        forbids a handler row with a null listener_id. The FK fallback nulls listener_id on the FK
        violation, which then fails the CHECK, so the row is dropped rather than orphaned. Under
        synchronous registration a listener is always persisted before it is routable, so this path
        does not occur in practice — but the repository must drop rather than corrupt on a stale FK.
        """
        db_svc, session_id = db
        nonexistent_listener_id = 99999
        record = make_inv_record(
            nonexistent_listener_id,
            session_id,
            execution_id="abc-123",
            trigger_context_id="ctx-456",
            trigger_origin="REMOTE",
        )

        dropped = await repo.persist_execution_batch_with_fk_fallback([record])
        assert dropped == [record]  # CHECK prevents a null-FK orphan; the row is dropped

        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 0  # no orphan row written

    async def test_shared_params_match_persist_batch_columns(self, db: DbFixture) -> None:
        """execution_insert_params() keys must match the executions table columns used in persist_batch()."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(
            listener_id, session_id, execution_id="abc-test", trigger_context_id="ctx-test", trigger_origin="LOCAL"
        )
        params = execution_insert_params(record)

        assert "kind" in params
        assert "execution_id" in params
        assert "trigger_context_id" in params
        assert "trigger_origin" in params
        assert "listener_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build the column list from keys — same as persist_execution_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        await db_svc.db.execute(
            f"INSERT INTO executions ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1


class TestJobExecutionExecutionId:
    async def test_persist_and_query_job_execution_with_execution_id(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """Persist a job ExecutionRecord with execution_id and query it back."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)
        record = make_job_record(job_id, session_id, execution_id="def-789")

        await repo.persist_execution_batch([record])

        je = await only_row(query_service.get_executions(job_id=job_id, kind="job", limit=10))
        assert je.execution_id == "def-789"
        assert je.trigger is None, "Job executions must have trigger=None"

    async def test_job_shared_params_match_persist_batch_columns(self, db: DbFixture) -> None:
        """execution_insert_params() keys for kind=job must match the executions table columns."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)
        record = make_job_record(job_id, session_id, execution_id="def-test")
        params = execution_insert_params(record)

        assert "kind" in params
        assert "execution_id" in params
        assert "job_id" in params
        assert "session_id" in params
        assert "is_di_failure" in params

        # is_di_failure must be int-converted (not bool)
        assert isinstance(params["is_di_failure"], int)

        # Build the column list from keys — same as persist_execution_batch() does
        cols = ", ".join(params.keys())
        vals = ", ".join(f":{k}" for k in params)

        await db_svc.db.execute(
            f"INSERT INTO executions ({cols}) VALUES ({vals})",
            params,
        )
        await db_svc.db.commit()

        async with db_svc.db.execute("SELECT COUNT(*) FROM executions") as cursor:
            count_row = await cursor.fetchone()
        assert count_row is not None
        assert count_row[0] == 1


class TestGetExecutionById:
    """Coverage for TelemetryQueryService.get_execution_by_id (execution_queries.py)."""

    async def test_returns_execution_when_found(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(
            listener_id,
            session_id,
            execution_id="find-me-abc",
            trigger_context_id="ctx-999",
            trigger_origin="REMOTE",
        )
        await repo.persist_execution_batch([record])

        result = await query_service.get_execution_by_id("find-me-abc")

        assert result is not None
        assert result.execution_id == "find-me-abc"
        assert result.trigger is not None
        assert result.trigger.context_id == "ctx-999"
        assert result.trigger.origin == "REMOTE"
        assert result.kind == "handler"
        assert result.listener_id == listener_id

    async def test_event_summary_round_trips_into_nested_trigger(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_execution_record(
            session_id=session_id,
            listener_id=listener_id,
            execution_id="summary-1",
            trigger_context_id="ctx-1",
            trigger_origin="LOCAL",
            trigger_parent_id="ctx-parent",
            trigger_topic="hass.event.state_changed",
            trigger_entity_id="light.office",
            trigger_old_value="off",
            trigger_new_value="on",
        )
        await repo.persist_execution_batch([record])

        result = await query_service.get_execution_by_id("summary-1")

        assert result is not None
        assert result.trigger == ExecutionTrigger(
            topic="hass.event.state_changed",
            entity_id="light.office",
            old_value="off",
            new_value="on",
            context_id="ctx-1",
            parent_id="ctx-parent",
            origin="LOCAL",
        )

    async def test_handler_row_without_summary_still_gets_trigger_object(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        """A row with only context and origin (pre-023, or a failed extraction) keeps both."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)
        record = make_inv_record(
            listener_id, session_id, execution_id="old-row", trigger_context_id="ctx-old", trigger_origin="LOCAL"
        )
        await repo.persist_execution_batch([record])

        result = await query_service.get_execution_by_id("old-row")

        assert result is not None
        assert result.trigger == ExecutionTrigger(context_id="ctx-old", origin="LOCAL")

    async def test_returns_none_when_not_found(self, db: DbFixture, query_service: TelemetryQueryService) -> None:
        result = await query_service.get_execution_by_id("nonexistent-id-xyz")
        assert result is None

    async def test_returns_job_execution(
        self, db: DbFixture, repo: TelemetryRepository, query_service: TelemetryQueryService
    ) -> None:
        db_svc, session_id = db
        job_id = await insert_job(db_svc)
        record = make_job_record(job_id, session_id, execution_id="job-exec-001")
        await repo.persist_execution_batch([record])

        result = await query_service.get_execution_by_id("job-exec-001")

        assert result is not None
        assert result.execution_id == "job-exec-001"
        assert result.kind == "job"
        assert result.job_id == job_id
