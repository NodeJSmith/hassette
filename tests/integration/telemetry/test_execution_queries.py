"""Integration tests for execution-level queries.

Covers get_executions() and get_slow_handlers().
"""

import time

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.execution_models import Execution

from .helpers import insert_execution, insert_invocation, insert_job, insert_listener


class TestGetExecutionsForListener:
    async def test_get_executions_handler_ordered(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """5 invocations at different timestamps — most recent first, limit respected."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)

        base_ts = time.time()
        for i in range(5):
            await insert_invocation(db_svc, listener_id, session_id, execution_start_ts=base_ts + i)

        # limit=3 returns 3 most recent
        rows = await query_service.get_executions(listener_id=listener_id, kind="handler", limit=3)
        assert len(rows) == 3
        assert all(isinstance(r, Execution) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 4)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 3)
        assert rows[2].execution_start_ts == pytest.approx(base_ts + 2)


class TestGetExecutionsForJob:
    async def test_get_executions_job_ordered(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """3 executions — ordered DESC, respects limit."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)

        base_ts = time.time()
        for i in range(3):
            await insert_execution(db_svc, job_id, session_id, execution_start_ts=base_ts + i)

        rows = await query_service.get_executions(job_id=job_id, kind="job", limit=2)
        assert len(rows) == 2
        assert all(isinstance(r, Execution) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 2)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 1)


class TestGetSlowHandlers:
    async def test_get_slow_handlers(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mix of fast + slow invocations — only above threshold returned, ordered by duration."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)

        await insert_invocation(db_svc, listener_id, session_id, duration_ms=5.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=100.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=500.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=50.0)

        rows = await query_service.get_slow_handlers(threshold_ms=60.0)
        assert len(rows) == 2
        assert rows[0].duration_ms == pytest.approx(500.0)
        assert rows[1].duration_ms == pytest.approx(100.0)
