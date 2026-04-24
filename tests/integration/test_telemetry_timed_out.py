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
from hassette.web.telemetry_helpers import compute_health_metrics

# ---------------------------------------------------------------------------
# Fixtures (mirrors test_telemetry_query_service.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hassette(tmp_path: Path) -> MagicMock:
    hassette = MagicMock()
    hassette.config.data_dir = tmp_path
    hassette.config.db_path = None
    hassette.config.db_retention_days = 7
    hassette.config.telemetry_write_queue_max = 500
    hassette.config.db_write_queue_max = 2000
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.web_api_log_level = "INFO"
    hassette.config.run_web_api = True
    hassette.config.db_migration_timeout_seconds = 120
    hassette.config.db_max_size_mb = 0
    hassette.ready_event = asyncio.Event()
    return hassette


@pytest.fixture
async def db(mock_hassette: MagicMock) -> AsyncIterator[tuple[DatabaseService, int]]:
    db_service = DatabaseService(mock_hassette, parent=mock_hassette)
    await db_service.on_initialize()
    cursor = await db_service.db.execute(
        "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
        (time.time(), time.time()),
    )
    session_id = cursor.lastrowid
    await db_service.db.commit()
    mock_hassette.session_id = session_id
    mock_hassette.database_service = db_service
    yield db_service, session_id
    await db_service.on_shutdown()


@pytest.fixture
def svc(mock_hassette: MagicMock, db: tuple[DatabaseService, int]) -> TelemetryQueryService:  # noqa: ARG001
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = mock_hassette
    service.logger = MagicMock()
    service._snapshot_lock = asyncio.Lock()
    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_listener(db_svc: DatabaseService, *, app_key: str = "test_app") -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, 0, 'on_event', 'state_changed.light.test', NULL, NULL, 0, 0, 'test.py:1', 'app')""",
        (app_key,),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_job(db_svc: DatabaseService, *, app_key: str = "test_app") -> int:
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, repeat, source_location, source_tier)
           VALUES (?, 0, 'my_job', 'run_job', 'interval', 1, 'test.py:1', 'app')""",
        (app_key,),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_invocation(
    db_svc: DatabaseService,
    listener_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 10.0,
) -> None:
    await db_svc.db.execute(
        """INSERT INTO handler_invocations
               (listener_id, session_id, execution_start_ts, duration_ms,
                status, source_tier)
           VALUES (?, ?, ?, ?, ?, 'app')""",
        (listener_id, session_id, time.time(), duration_ms, status),
    )
    await db_svc.db.commit()


async def _insert_execution(
    db_svc: DatabaseService,
    job_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 20.0,
) -> None:
    await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, source_tier)
           VALUES (?, ?, ?, ?, ?, 'app')""",
        (job_id, session_id, time.time(), duration_ms, status),
    )
    await db_svc.db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestListenerSummaryTimedOut:
    async def test_listener_summary_counts_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is a separate bucket in ListenerSummary."""
        db_svc, session_id = db
        lid = await _insert_listener(db_svc)
        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_invocation(db_svc, lid, session_id, status="error")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")

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
        jid = await _insert_job(db_svc)
        await _insert_execution(db_svc, jid, session_id, status="success")
        await _insert_execution(db_svc, jid, session_id, status="success")
        await _insert_execution(db_svc, jid, session_id, status="error")
        await _insert_execution(db_svc, jid, session_id, status="timed_out")

        summaries = await svc.get_job_summary("test_app", 0)
        assert len(summaries) == 1
        s = summaries[0]
        assert s.total_executions == 4
        assert s.successful == 2
        assert s.failed == 1
        assert s.timed_out == 1


class TestGlobalSummaryTimedOut:
    async def test_global_summary_separates_timed_out_from_errors(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify timed_out is counted separately from errors in global summary."""
        db_svc, session_id = db
        lid = await _insert_listener(db_svc)
        jid = await _insert_job(db_svc)

        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")
        await _insert_execution(db_svc, jid, session_id, status="error")
        await _insert_execution(db_svc, jid, session_id, status="timed_out")

        summary = await svc.get_global_summary()
        assert summary.listeners.total_errors == 0
        assert summary.listeners.total_timed_out == 1
        assert summary.jobs.total_errors == 1
        assert summary.jobs.total_timed_out == 1


class TestErrorRateIncludesTimedOut:
    async def test_error_rate_includes_timed_out_as_failure(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify compute_health_metrics treats timed_out as a failure subtype."""
        db_svc, session_id = db
        lid = await _insert_listener(db_svc)
        jid = await _insert_job(db_svc)

        # 2 success, 1 error, 1 timed_out = 50% error rate for handlers
        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_invocation(db_svc, lid, session_id, status="error")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")

        # 1 success, 1 timed_out = 50% error rate for jobs
        await _insert_execution(db_svc, jid, session_id, status="success")
        await _insert_execution(db_svc, jid, session_id, status="timed_out")

        listeners = await svc.get_listener_summary("test_app", 0)
        jobs = await svc.get_job_summary("test_app", 0)
        metrics = compute_health_metrics(listeners, jobs)

        # Combined: 6 total, 3 failures (1 error + 1 timed_out handler + 1 timed_out job) = 50%
        assert metrics["error_rate"] == pytest.approx(50.0)


class TestErrorCountsIncludeTimedOut:
    async def test_error_counts_include_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify get_error_counts includes timed_out records."""
        db_svc, session_id = db
        lid = await _insert_listener(db_svc)
        jid = await _insert_job(db_svc)

        since_ts = time.time() - 1
        await _insert_invocation(db_svc, lid, session_id, status="error")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")
        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_execution(db_svc, jid, session_id, status="timed_out")

        handler_errors, job_errors = await svc.get_error_counts(since_ts)
        assert handler_errors == 2  # error + timed_out
        assert job_errors == 1  # timed_out


class TestRecentErrorsIncludeTimedOut:
    async def test_recent_errors_include_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Verify get_recent_errors returns timed_out records."""
        db_svc, session_id = db
        lid = await _insert_listener(db_svc)

        since_ts = time.time() - 1
        await _insert_invocation(db_svc, lid, session_id, status="success")
        await _insert_invocation(db_svc, lid, session_id, status="timed_out")

        errors = await svc.get_recent_errors(since_ts)
        assert len(errors) == 1
        assert errors[0].kind == "handler"
