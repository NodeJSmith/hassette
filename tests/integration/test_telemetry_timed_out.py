"""Integration tests for timed_out status in telemetry queries.

Verifies that 'timed_out' is counted as a separate bucket in summaries
and treated as a failure subtype in error-rate calculations.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_query_service import TelemetryQueryService
from hassette.test_utils.mock_hassette import make_mock_hassette
from hassette.web.telemetry_helpers import compute_health_metrics

from .telemetry_query_helpers import insert_execution, insert_invocation, insert_job, insert_listener


@pytest.fixture
def db_hassette(premigrated_db_path: Path) -> MagicMock:
    return make_mock_hassette(
        data_dir=premigrated_db_path.parent,
        set_ready=False,
        database={"telemetry_write_queue_max": 500, "max_size_mb": 0},
        lifecycle={"resource_shutdown_timeout_seconds": 5},
        web_api={"run": True},
    )


@pytest.fixture
async def db(db_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    db_service = DatabaseService(db_hassette, parent=None)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    db_hassette.session_id = session_id
    db_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def svc(db_hassette: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = db_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


class TestListenerSummaryTimedOut:
    async def test_listener_summary_counts_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is a separate bucket in ListenerSummary."""
        db_svc, session_id = db
        lid = await insert_listener(db_svc)
        await insert_invocation(db_svc, lid, session_id, status="success")
        await insert_invocation(db_svc, lid, session_id, status="error")
        await insert_invocation(db_svc, lid, session_id, status="timed_out")
        await insert_invocation(db_svc, lid, session_id, status="timed_out")

        summaries = await svc.get_listener_summary("test_app", 0)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.total_invocations == 4
        assert s.successful == 1
        assert s.failed == 1
        assert s.timed_out == 2
        assert s.cancelled == 0


class TestJobSummaryTimedOut:
    async def test_job_summary_counts_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is a separate bucket in JobSummary."""
        db_svc, session_id = db
        jid = await insert_job(db_svc)
        await insert_execution(db_svc, jid, session_id, status="success")
        await insert_execution(db_svc, jid, session_id, status="success")
        await insert_execution(db_svc, jid, session_id, status="error")
        await insert_execution(db_svc, jid, session_id, status="timed_out")

        summaries = await svc.get_job_summary("test_app", 0)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.total_executions == 4
        assert s.successful == 2
        assert s.failed == 1
        assert s.timed_out == 1


class TestErrorRateIncludesTimedOut:
    async def test_error_rate_includes_timed_out_as_failure(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify compute_health_metrics treats timed_out as a failure subtype."""
        db_svc, session_id = db
        lid = await insert_listener(db_svc)
        jid = await insert_job(db_svc)

        # 2 success, 1 error, 1 timed_out = 50% error rate for handlers
        await insert_invocation(db_svc, lid, session_id, status="success")
        await insert_invocation(db_svc, lid, session_id, status="success")
        await insert_invocation(db_svc, lid, session_id, status="error")
        await insert_invocation(db_svc, lid, session_id, status="timed_out")

        # 1 success, 1 timed_out = 50% error rate for jobs
        await insert_execution(db_svc, jid, session_id, status="success")
        await insert_execution(db_svc, jid, session_id, status="timed_out")

        listeners = await svc.get_listener_summary("test_app", 0)
        jobs = await svc.get_job_summary("test_app", 0)
        metrics = compute_health_metrics(listeners, jobs)

        # Combined: 6 total, 3 failures (1 error + 1 timed_out handler + 1 timed_out job) = 50%
        assert metrics["error_rate"] == pytest.approx(50.0)
