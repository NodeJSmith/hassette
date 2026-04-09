"""Integration tests for TelemetryQueryService with real SQLite database."""

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionRecord,
)
from hassette.core.telemetry_query_service import TelemetryQueryService

# ---------------------------------------------------------------------------
# Fixtures
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
    """Initialize a DatabaseService with a seeded session row.

    Yields:
        Tuple of (DatabaseService instance, session_id).
    """
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
    """Create a TelemetryQueryService with DatabaseService already wired.

    Skips on_initialize (which waits on DatabaseService) since the fixture
    provides it directly via mock_hassette.database_service.
    """
    service = TelemetryQueryService.__new__(TelemetryQueryService)
    service.hassette = mock_hassette
    service.logger = MagicMock()
    return service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_listener(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    handler_method: str = "on_event",
    topic: str = "hass.event.state_changed",
    source_tier: str = "app",
) -> int:
    """Insert a listener row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, 'test.py:1', ?)""",
        (app_key, instance_index, handler_method, topic, source_tier),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_job(
    db_svc: DatabaseService,
    *,
    app_key: str = "test_app",
    instance_index: int = 0,
    job_name: str = "my_job",
    handler_method: str = "run_job",
    source_tier: str = "app",
) -> int:
    """Insert a scheduled_job row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, trigger_value, repeat,
                source_location, source_tier)
           VALUES (?, ?, ?, ?, 'interval', '60', 1, 'test.py:1', ?)""",
        (app_key, instance_index, job_name, handler_method, source_tier),
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
    error_type: str | None = None,
    error_message: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
    is_di_failure: int = 0,
) -> int:
    """Insert a handler_invocations row and return its id."""
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO handler_invocations
               (listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (listener_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier, is_di_failure),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


async def _insert_execution(
    db_svc: DatabaseService,
    job_id: int,
    session_id: int,
    *,
    status: str = "success",
    duration_ms: float = 20.0,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_start_ts: float | None = None,
    source_tier: str = "app",
    is_di_failure: int = 0,
) -> int:
    """Insert a job_executions row and return its id."""
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message, source_tier, is_di_failure)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (job_id, session_id, ts, duration_ms, status, error_type, error_message, source_tier, is_di_failure),
    )
    await db_svc.db.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


# ---------------------------------------------------------------------------
# Tests: get_listener_summary
# ---------------------------------------------------------------------------


class TestGetListenerSummary:
    async def test_get_listener_summary_aggregates(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 listeners, 3 invocations (2 success, 1 error) — correct aggregates."""
        db_svc, session_id = db

        l1 = await _insert_listener(db_svc, handler_method="on_a")
        _l2 = await _insert_listener(db_svc, handler_method="on_b")

        await _insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await _insert_invocation(db_svc, l1, session_id, status="success", duration_ms=20.0)
        await _insert_invocation(db_svc, l1, session_id, status="error", duration_ms=5.0, error_type="ValueError")

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 2

        assert all(isinstance(r, ListenerSummary) for r in rows)
        row = next(r for r in rows if r.handler_method == "on_a")
        assert row.total_invocations == 3
        assert row.successful == 2
        assert row.failed == 1
        assert row.avg_duration_ms == pytest.approx((10.0 + 20.0 + 5.0) / 3)

    async def test_get_listener_summary_empty(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """1 listener with no invocations — appears in results with zero counts."""
        db_svc, _session_id = db
        await _insert_listener(db_svc, handler_method="on_idle")

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 0
        assert row.successful == 0
        assert row.failed == 0

    async def test_get_listener_summary_session_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 invocations in session A, 1 in session B — session filter returns A only."""
        db_svc, session_a = db

        # Create a second session
        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        listener_id = await _insert_listener(db_svc, handler_method="on_event")
        await _insert_invocation(db_svc, listener_id, session_a, status="success")
        await _insert_invocation(db_svc, listener_id, session_a, status="success")
        await _insert_invocation(db_svc, listener_id, session_b, status="error")

        rows = await svc.get_listener_summary("test_app", 0, session_id=session_a)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 2
        assert row.successful == 2
        assert row.failed == 0


# ---------------------------------------------------------------------------
# Tests: get_job_summary
# ---------------------------------------------------------------------------


class TestGetJobSummary:
    async def test_get_job_summary_aggregates(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 jobs, mixed results — correct aggregate totals."""
        db_svc, session_id = db

        j1 = await _insert_job(db_svc, job_name="job_a")
        j2 = await _insert_job(db_svc, job_name="job_b")

        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await _insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)
        await _insert_execution(db_svc, j2, session_id, status="success", duration_ms=200.0)

        rows = await svc.get_job_summary("test_app", 0)
        assert len(rows) == 2

        assert all(isinstance(r, JobSummary) for r in rows)
        row1 = next(r for r in rows if r.job_name == "job_a")
        assert row1.job_id == j1
        assert row1.app_key == "test_app"
        assert row1.instance_index == 0
        assert row1.total_executions == 2
        assert row1.successful == 1
        assert row1.failed == 1
        assert row1.avg_duration_ms == pytest.approx(75.0)

        row2 = next(r for r in rows if r.job_name == "job_b")
        assert row2.job_id == j2
        assert row2.total_executions == 1
        assert row2.successful == 1
        assert row2.failed == 0


# ---------------------------------------------------------------------------
# Tests: get_global_summary
# ---------------------------------------------------------------------------


class TestGetGlobalSummary:
    async def test_get_global_summary(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mixed listener + job records — correct combined totals."""
        db_svc, session_id = db

        l1 = await _insert_listener(db_svc, handler_method="on_a")
        j1 = await _insert_job(db_svc, job_name="job_a")

        await _insert_invocation(db_svc, l1, session_id, status="success")
        await _insert_invocation(db_svc, l1, session_id, status="error")
        await _insert_execution(db_svc, j1, session_id, status="success")
        await _insert_execution(db_svc, j1, session_id, status="error")

        result = await svc.get_global_summary()
        assert isinstance(result, GlobalSummary)

        assert result.listeners.total_listeners == 1
        assert result.listeners.total_invocations == 2
        assert result.listeners.total_errors == 1

        assert result.jobs.total_jobs == 1
        assert result.jobs.total_executions == 2
        assert result.jobs.total_errors == 1


# ---------------------------------------------------------------------------
# Tests: get_handler_invocations
# ---------------------------------------------------------------------------


class TestGetHandlerInvocations:
    async def test_get_handler_invocations_ordered(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """5 invocations at different timestamps — most recent first, limit respected."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)

        base_ts = time.time()
        for i in range(5):
            await _insert_invocation(db_svc, listener_id, session_id, execution_start_ts=base_ts + i)

        # limit=3 returns 3 most recent
        rows = await svc.get_handler_invocations(listener_id, limit=3)
        assert len(rows) == 3
        assert all(isinstance(r, HandlerInvocation) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 4)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 3)
        assert rows[2].execution_start_ts == pytest.approx(base_ts + 2)


# ---------------------------------------------------------------------------
# Tests: get_job_executions
# ---------------------------------------------------------------------------


class TestGetJobExecutions:
    async def test_get_job_executions_ordered(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """3 executions — ordered DESC, respects limit."""
        db_svc, session_id = db
        job_id = await _insert_job(db_svc)

        base_ts = time.time()
        for i in range(3):
            await _insert_execution(db_svc, job_id, session_id, execution_start_ts=base_ts + i)

        rows = await svc.get_job_executions(job_id, limit=2)
        assert len(rows) == 2
        assert all(isinstance(r, JobExecution) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 2)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 1)


# ---------------------------------------------------------------------------
# Tests: get_recent_errors
# ---------------------------------------------------------------------------


class TestGetRecentErrors:
    async def test_get_recent_errors_filter(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mix of success + error records, some old — only errors after since_ts returned."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        job_id = await _insert_job(db_svc)

        base_ts = 1_000_000.0
        since_ts = base_ts + 5.0

        # Old error (before since_ts) — should NOT appear
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 1.0)
        # Recent success — should NOT appear
        await _insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 10.0)
        # Recent error — SHOULD appear
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 20.0)
        # Recent job error — SHOULD appear
        await _insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + 15.0)

        rows = await svc.get_recent_errors(since_ts)
        # Both handler error and job error should appear
        assert len(rows) == 2
        handler_rows = [r for r in rows if isinstance(r, HandlerErrorRecord)]
        job_rows = [r for r in rows if isinstance(r, JobErrorRecord)]
        assert len(handler_rows) == 1
        assert len(job_rows) == 1

        # Verify listener_id/job_id and execution_start_ts are present and non-zero
        assert handler_rows[0].listener_id > 0
        assert handler_rows[0].execution_start_ts > 0

        assert job_rows[0].job_id > 0
        assert job_rows[0].execution_start_ts > 0

    async def test_get_recent_errors_session_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Errors in two sessions — session filter applied."""
        db_svc, session_a = db

        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        listener_id = await _insert_listener(db_svc)
        base_ts = 1_000_000.0
        since_ts = base_ts - 1.0

        await _insert_invocation(db_svc, listener_id, session_a, status="error", execution_start_ts=base_ts + 1.0)
        await _insert_invocation(db_svc, listener_id, session_b, status="error", execution_start_ts=base_ts + 2.0)

        rows = await svc.get_recent_errors(since_ts, session_id=session_a)
        assert len(rows) == 1
        assert isinstance(rows[0], HandlerErrorRecord)


# ---------------------------------------------------------------------------
# Tests: get_slow_handlers
# ---------------------------------------------------------------------------


class TestGetSlowHandlers:
    async def test_get_slow_handlers(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mix of fast + slow invocations — only above threshold returned, ordered by duration."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)

        await _insert_invocation(db_svc, listener_id, session_id, duration_ms=5.0)
        await _insert_invocation(db_svc, listener_id, session_id, duration_ms=100.0)
        await _insert_invocation(db_svc, listener_id, session_id, duration_ms=500.0)
        await _insert_invocation(db_svc, listener_id, session_id, duration_ms=50.0)

        rows = await svc.get_slow_handlers(threshold_ms=60.0)
        assert len(rows) == 2
        assert rows[0].duration_ms == pytest.approx(500.0)
        assert rows[1].duration_ms == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Tests: get_session_list
# ---------------------------------------------------------------------------


class TestGetSessionList:
    async def test_get_session_list(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """3 sessions with different statuses — ordered by started_at DESC, correct duration."""
        db_svc, session_id = db

        base_ts = 1_000_000.0

        # Update the existing running session's started_at for predictability
        await db_svc.db.execute(
            "UPDATE sessions SET started_at = ?, last_heartbeat_at = ? WHERE id = ?",
            (base_ts + 200.0, base_ts + 300.0, session_id),
        )
        # Insert two more sessions
        await db_svc.db.execute(
            "INSERT INTO sessions (started_at, stopped_at, last_heartbeat_at, status) VALUES (?, ?, ?, 'stopped')",
            (base_ts + 100.0, base_ts + 150.0, base_ts + 150.0),
        )
        await db_svc.db.execute(
            "INSERT INTO sessions (started_at, stopped_at, last_heartbeat_at, status) VALUES (?, ?, ?, 'stopped')",
            (base_ts + 0.0, base_ts + 50.0, base_ts + 50.0),
        )
        await db_svc.db.commit()

        rows = await svc.get_session_list(limit=20)
        assert len(rows) == 3

        # Returns typed SessionRecord models
        assert all(isinstance(r, SessionRecord) for r in rows)

        # Most recent first: started_at DESC
        assert rows[0].started_at == pytest.approx(base_ts + 200.0)
        assert rows[1].started_at == pytest.approx(base_ts + 100.0)
        assert rows[2].started_at == pytest.approx(base_ts + 0.0)

        # duration_seconds for stopped sessions = stopped_at - started_at
        assert rows[1].duration_seconds == pytest.approx(50.0)
        assert rows[2].duration_seconds == pytest.approx(50.0)

        # Running session uses last_heartbeat_at for duration
        assert rows[0].duration_seconds == pytest.approx(100.0)

        # Field types are correct
        assert isinstance(rows[0].id, int)
        assert isinstance(rows[0].status, str)
        assert rows[0].stopped_at is None  # running session
        assert rows[1].stopped_at is not None  # stopped session


# ---------------------------------------------------------------------------
# Tests: get_all_app_summaries
# ---------------------------------------------------------------------------


class TestGetAllAppSummaries:
    async def test_get_all_app_summaries_returns_dict(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Two apps with listeners and jobs — returns dict[str, AppHealthSummary]."""
        db_svc, session_id = db

        # App A: 2 listeners, 1 job
        l1 = await _insert_listener(db_svc, app_key="app_a", handler_method="on_a")
        l2 = await _insert_listener(db_svc, app_key="app_a", handler_method="on_b")
        j1 = await _insert_job(db_svc, app_key="app_a", job_name="job_a")

        await _insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await _insert_invocation(db_svc, l1, session_id, status="error", duration_ms=20.0)
        await _insert_invocation(db_svc, l2, session_id, status="success", duration_ms=30.0)
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await _insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)

        # App B: 1 listener, 0 jobs
        l3 = await _insert_listener(db_svc, app_key="app_b", handler_method="on_c")
        await _insert_invocation(db_svc, l3, session_id, status="success", duration_ms=5.0)

        result = await svc.get_all_app_summaries()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"app_a", "app_b"}

        a = result["app_a"]
        assert isinstance(a, AppHealthSummary)
        assert a.handler_count == 2
        assert a.job_count == 1
        assert a.total_invocations == 3
        assert a.total_errors == 1
        assert a.total_executions == 2
        assert a.total_job_errors == 1
        assert a.avg_duration_ms == pytest.approx(20.0)  # (10+20+30)/3
        assert a.last_activity_ts is not None

        b = result["app_b"]
        assert isinstance(b, AppHealthSummary)
        assert b.handler_count == 1
        assert b.job_count == 0
        assert b.total_invocations == 1
        assert b.total_errors == 0
        assert b.total_executions == 0
        assert b.total_job_errors == 0

    async def test_get_all_app_summaries_empty_db(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """No listeners or jobs — returns empty dict."""
        result = await svc.get_all_app_summaries()
        assert result == {}

    async def test_get_all_app_summaries_session_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Session filter restricts invocation/execution counts."""
        db_svc, session_a = db

        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        l1 = await _insert_listener(db_svc, app_key="app_x", handler_method="on_a")
        j1 = await _insert_job(db_svc, app_key="app_x", job_name="job_a")

        # Session A: 2 invocations (1 error), 1 execution
        await _insert_invocation(db_svc, l1, session_a, status="success")
        await _insert_invocation(db_svc, l1, session_a, status="error")
        await _insert_execution(db_svc, j1, session_a, status="success")

        # Session B: 1 invocation, 1 execution (error)
        await _insert_invocation(db_svc, l1, session_b, status="success")
        await _insert_execution(db_svc, j1, session_b, status="error")

        result = await svc.get_all_app_summaries(session_id=session_a)
        assert "app_x" in result
        x = result["app_x"]
        assert x.total_invocations == 2
        assert x.total_errors == 1
        assert x.total_executions == 1
        assert x.total_job_errors == 0

    async def test_get_all_app_summaries_multi_instance_activity_aggregation(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance app: activity sums across all instances, handler_count reflects instance 0 only."""
        db_svc, session_id = db

        # Instance 0: 2 listeners, 2 invocations
        l0a = await _insert_listener(db_svc, app_key="app_m", instance_index=0, handler_method="on_a")
        l0b = await _insert_listener(db_svc, app_key="app_m", instance_index=0, handler_method="on_b")
        await _insert_invocation(db_svc, l0a, session_id, status="success", duration_ms=10.0)
        await _insert_invocation(db_svc, l0b, session_id, status="error", duration_ms=20.0)

        # Instance 1: 2 listeners (same handlers, different instance), 3 invocations
        l1a = await _insert_listener(db_svc, app_key="app_m", instance_index=1, handler_method="on_a")
        l1b = await _insert_listener(db_svc, app_key="app_m", instance_index=1, handler_method="on_b")
        await _insert_invocation(db_svc, l1a, session_id, status="success", duration_ms=30.0)
        await _insert_invocation(db_svc, l1b, session_id, status="success", duration_ms=40.0)
        await _insert_invocation(db_svc, l1b, session_id, status="error", duration_ms=50.0)

        # Instance 2: 1 listener, 1 invocation
        l2a = await _insert_listener(db_svc, app_key="app_m", instance_index=2, handler_method="on_a")
        await _insert_invocation(db_svc, l2a, session_id, status="success", duration_ms=60.0)

        result = await svc.get_all_app_summaries()
        assert "app_m" in result
        m = result["app_m"]

        # handler_count reflects instance 0 only (2 listeners)
        assert m.handler_count == 2
        # total_invocations sums across ALL instances: 2 + 3 + 1 = 6
        assert m.total_invocations == 6
        # total_errors sums across ALL instances: 1 + 1 = 2
        assert m.total_errors == 2
        # avg_duration_ms is AVG over all 6 raw rows: (10+20+30+40+50+60)/6 = 35.0
        assert m.avg_duration_ms == pytest.approx(35.0)

    async def test_get_all_app_summaries_multi_instance_job_aggregation(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance app: job activity sums across all instances, job_count reflects instance 0 only."""
        db_svc, session_id = db

        # Instance 0: 1 job, 2 executions
        j0 = await _insert_job(db_svc, app_key="app_j", instance_index=0, job_name="cron_a")
        await _insert_execution(db_svc, j0, session_id, status="success", duration_ms=100.0)
        await _insert_execution(db_svc, j0, session_id, status="error", duration_ms=50.0)

        # Instance 1: 1 job, 3 executions
        j1 = await _insert_job(db_svc, app_key="app_j", instance_index=1, job_name="cron_a")
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=200.0)
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=150.0)
        await _insert_execution(db_svc, j1, session_id, status="error", duration_ms=80.0)

        # Instance 2: 1 job, 1 execution
        j2 = await _insert_job(db_svc, app_key="app_j", instance_index=2, job_name="cron_a")
        await _insert_execution(db_svc, j2, session_id, status="success", duration_ms=300.0)

        result = await svc.get_all_app_summaries()
        assert "app_j" in result
        j = result["app_j"]

        # job_count reflects instance 0 only (1 job)
        assert j.job_count == 1
        # total_executions sums across ALL instances: 2 + 3 + 1 = 6
        assert j.total_executions == 6
        # total_job_errors sums across ALL instances: 1 + 1 = 2
        assert j.total_job_errors == 2

    async def test_get_all_app_summaries_single_instance_equivalence(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Single-instance app produces equivalent results to current behavior."""
        db_svc, session_id = db

        # Only instance 0 — same as current behavior
        l1 = await _insert_listener(db_svc, app_key="app_s", instance_index=0, handler_method="on_x")
        j1 = await _insert_job(db_svc, app_key="app_s", instance_index=0, job_name="job_x")

        await _insert_invocation(db_svc, l1, session_id, status="success", duration_ms=15.0)
        await _insert_invocation(db_svc, l1, session_id, status="error", duration_ms=25.0)
        await _insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)

        result = await svc.get_all_app_summaries()
        assert "app_s" in result
        s = result["app_s"]

        assert s.handler_count == 1
        assert s.job_count == 1
        assert s.total_invocations == 2
        assert s.total_errors == 1
        assert s.total_executions == 1
        assert s.total_job_errors == 0
        assert s.avg_duration_ms == pytest.approx(20.0, abs=0.001)

    async def test_get_all_app_summaries_multi_instance_session_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multi-instance data across sessions: session-scoped variant aggregates correctly."""
        db_svc, session_a = db

        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        # Instance 0: listener + job
        l0 = await _insert_listener(db_svc, app_key="app_ms", instance_index=0, handler_method="on_a")
        j0 = await _insert_job(db_svc, app_key="app_ms", instance_index=0, job_name="cron_a")

        # Instance 1: listener + job
        l1 = await _insert_listener(db_svc, app_key="app_ms", instance_index=1, handler_method="on_a")
        j1 = await _insert_job(db_svc, app_key="app_ms", instance_index=1, job_name="cron_a")

        # Session A: instance 0 gets 2 invocations, instance 1 gets 1 invocation
        await _insert_invocation(db_svc, l0, session_a, status="success", duration_ms=10.0)
        await _insert_invocation(db_svc, l0, session_a, status="error", duration_ms=20.0)
        await _insert_invocation(db_svc, l1, session_a, status="success", duration_ms=30.0)
        await _insert_execution(db_svc, j0, session_a, status="success")
        await _insert_execution(db_svc, j1, session_a, status="error")

        # Session B: instance 0 gets 1 invocation (should NOT be counted for session A)
        await _insert_invocation(db_svc, l0, session_b, status="success", duration_ms=100.0)
        await _insert_execution(db_svc, j0, session_b, status="error")

        result = await svc.get_all_app_summaries(session_id=session_a)
        assert "app_ms" in result
        ms = result["app_ms"]

        # handler_count from instance 0 only
        assert ms.handler_count == 1
        # job_count from instance 0 only
        assert ms.job_count == 1
        # total_invocations: session A across all instances = 2 + 1 = 3
        assert ms.total_invocations == 3
        # total_errors: session A across all instances = 1
        assert ms.total_errors == 1
        # total_executions: session A across all instances = 1 + 1 = 2
        assert ms.total_executions == 2
        # total_job_errors: session A across all instances = 1
        assert ms.total_job_errors == 1
        # avg_duration_ms: session A across all instances = (10+20+30)/3 = 20.0
        assert ms.avg_duration_ms == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Tests: get_global_summary returns typed model
# ---------------------------------------------------------------------------


class TestGetGlobalSummaryTyped:
    async def test_get_global_summary_returns_typed_model(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary returns GlobalSummary, not dict."""
        db_svc, session_id = db

        l1 = await _insert_listener(db_svc, handler_method="on_a")
        j1 = await _insert_job(db_svc, job_name="job_a")
        await _insert_invocation(db_svc, l1, session_id, status="success")
        await _insert_execution(db_svc, j1, session_id, status="success")

        result = await svc.get_global_summary()
        assert isinstance(result, GlobalSummary)
        assert result.listeners.total_listeners == 1
        assert result.listeners.total_invocations == 1
        assert result.jobs.total_jobs == 1
        assert result.jobs.total_executions == 1

    async def test_get_global_summary_fresh_install(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Fresh install with no telemetry data — returns zero-value GlobalSummary."""
        result = await svc.get_global_summary()
        assert isinstance(result, GlobalSummary)
        assert result.listeners.total_listeners == 0
        assert result.listeners.total_invocations == 0
        assert result.listeners.avg_duration_ms is None
        assert result.jobs.total_jobs == 0
        assert result.jobs.total_executions == 0


# ---------------------------------------------------------------------------
# Tests: cross-session aggregation and retired-row view enforcement (WP06)
# ---------------------------------------------------------------------------


class TestCrossSessionAndRetiredRows:
    async def test_all_time_aggregates_across_sessions(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All-time query (no session_id) spans multiple sessions.

        Register a listener in session 1, create invocations, then simulate
        a restart (upsert the same row in session 2 by re-inserting with a new
        session), create more invocations, and assert the all-time total covers
        both sessions.
        """
        db_svc, session_1 = db

        # Create session 2 (simulates a restart)
        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'running')",
            (time.time(), time.time()),
        )
        session_2 = cursor.lastrowid
        await db_svc.db.commit()

        # Session 1: register listener and create 2 invocations
        listener_id = await _insert_listener(db_svc, handler_method="on_event")
        await _insert_invocation(db_svc, listener_id, session_1, status="success")
        await _insert_invocation(db_svc, listener_id, session_1, status="error")

        # Session 2: same listener row (FK still valid), 3 more invocations
        await _insert_invocation(db_svc, listener_id, session_2, status="success")
        await _insert_invocation(db_svc, listener_id, session_2, status="success")
        await _insert_invocation(db_svc, listener_id, session_2, status="success")

        # All-time query must aggregate across both sessions
        summary = await svc.get_listener_summary("test_app", 0)
        assert len(summary) == 1
        row = summary[0]
        assert row.total_invocations == 5
        assert row.successful == 4
        assert row.failed == 1

    async def test_registration_counts_exclude_retired(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary total_listeners uses active_listeners view (excludes retired rows).

        Register two listeners. Mark one retired via retired_at. The global summary
        must report total_listeners = 1.
        """
        db_svc, _session_id = db

        await _insert_listener(db_svc, handler_method="on_active")
        retired_id = await _insert_listener(db_svc, handler_method="on_retired")

        # Mark the second listener as retired
        now = time.time()
        await db_svc.db.execute(
            "UPDATE listeners SET retired_at = ? WHERE id = ?",
            (now, retired_id),
        )
        await db_svc.db.commit()

        result = await svc.get_global_summary()
        assert result.listeners.total_listeners == 1

    async def test_listener_summary_includes_retired(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_listener_summary queries base tables and includes retired rows.

        A retired listener with invocation history must still appear in the summary.
        """
        db_svc, session_id = db

        retired_id = await _insert_listener(db_svc, handler_method="on_retired")
        await _insert_invocation(db_svc, retired_id, session_id, status="success")
        await _insert_invocation(db_svc, retired_id, session_id, status="error")

        # Mark as retired
        now = time.time()
        await db_svc.db.execute(
            "UPDATE listeners SET retired_at = ? WHERE id = ?",
            (now, retired_id),
        )
        await db_svc.db.commit()

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.handler_method == "on_retired"
        assert row.total_invocations == 2
        assert row.successful == 1
        assert row.failed == 1

    async def test_retention_cleanup_deletes_old_retired_rows(
        self,
        db: tuple[DatabaseService, int],
    ) -> None:
        """_do_run_retention_cleanup deletes retired registration rows older than retention_days.

        Insert a listener and a scheduled_job with old retired_at timestamps and
        a recent one. After cleanup, the old ones must be deleted and the recent
        one preserved.
        """
        db_svc, _session_id = db

        now = time.time()
        old_retired_at = now - (8 * 86400)  # 8 days ago — beyond 7-day retention
        recent_retired_at = now - (1 * 86400)  # 1 day ago — within retention

        # Insert old retired listener (no invocations needed)
        cursor = await db_svc.db.execute(
            "INSERT INTO listeners (app_key, instance_index, handler_method, topic, "
            "debounce, throttle, once, priority, source_location, retired_at) "
            "VALUES ('test_app', 0, 'on_old', 'hass.event', NULL, NULL, 0, 0, 'test.py:1', ?)",
            (old_retired_at,),
        )
        old_listener_id = cursor.lastrowid

        # Insert recent retired listener (should survive cleanup)
        cursor = await db_svc.db.execute(
            "INSERT INTO listeners (app_key, instance_index, handler_method, topic, "
            "debounce, throttle, once, priority, source_location, retired_at) "
            "VALUES ('test_app', 0, 'on_recent', 'hass.event', NULL, NULL, 0, 0, 'test.py:2', ?)",
            (recent_retired_at,),
        )
        recent_listener_id = cursor.lastrowid

        # Insert old retired scheduled_job
        cursor = await db_svc.db.execute(
            "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, "
            "trigger_type, trigger_value, repeat, source_location, retired_at) "
            "VALUES ('test_app', 0, 'old_job', 'run_old', 'interval', '60', 1, 'test.py:3', ?)",
            (old_retired_at,),
        )
        old_job_id = cursor.lastrowid

        # Insert recent retired scheduled_job (should survive cleanup)
        cursor = await db_svc.db.execute(
            "INSERT INTO scheduled_jobs (app_key, instance_index, job_name, handler_method, "
            "trigger_type, trigger_value, repeat, source_location, retired_at) "
            "VALUES ('test_app', 0, 'recent_job', 'run_recent', 'interval', '60', 1, 'test.py:4', ?)",
            (recent_retired_at,),
        )
        recent_job_id = cursor.lastrowid

        await db_svc.db.commit()

        # Run retention cleanup
        await db_svc._do_run_retention_cleanup()

        # Old retired rows must be deleted
        cursor = await db_svc.db.execute("SELECT id FROM listeners WHERE id = ?", (old_listener_id,))
        assert await cursor.fetchone() is None, "Old retired listener must be deleted"

        cursor = await db_svc.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (old_job_id,))
        assert await cursor.fetchone() is None, "Old retired job must be deleted"

        # Recent retired rows must be preserved
        cursor = await db_svc.db.execute("SELECT id FROM listeners WHERE id = ?", (recent_listener_id,))
        assert await cursor.fetchone() is not None, "Recent retired listener must survive"

        cursor = await db_svc.db.execute("SELECT id FROM scheduled_jobs WHERE id = ?", (recent_job_id,))
        assert await cursor.fetchone() is not None, "Recent retired job must survive"


# ---------------------------------------------------------------------------
# Tests: WP05 — source_tier filtering, UNION ALL, LEFT JOIN, is_di_failure
# ---------------------------------------------------------------------------


class TestGetRecentErrorsUnionAll:
    async def test_get_recent_errors_union_all_ordering(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mixed handler/job errors with known timestamps — verify correct ordering."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, handler_method="on_a")
        job_id = await _insert_job(db_svc, job_name="job_a")

        base_ts = 2_000_000.0
        # Insert handler errors at t=1,3,5 and job errors at t=2,4
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 5.0)
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 3.0)
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 1.0)
        await _insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + 4.0)
        await _insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + 2.0)

        rows = await svc.get_recent_errors(since_ts=base_ts)
        assert len(rows) == 5
        # Must be sorted DESC by execution_start_ts across both types
        ts_values = [r.execution_start_ts for r in rows]
        assert ts_values == sorted(ts_values, reverse=True)
        assert ts_values[0] == pytest.approx(base_ts + 5.0)
        assert ts_values[1] == pytest.approx(base_ts + 4.0)
        assert ts_values[2] == pytest.approx(base_ts + 3.0)

    async def test_get_recent_errors_limit_applies_globally(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """20 handler + 5 job errors, limit=10 → 10 most recent total."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc)
        job_id = await _insert_job(db_svc)

        base_ts = 3_000_000.0
        # Handler errors at offsets 0..19 (ts 0-19)
        for i in range(20):
            await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + i)
        # Job errors at offsets 20..24 (ts 20-24) — most recent
        for i in range(20, 25):
            await _insert_execution(db_svc, job_id, session_id, status="error", execution_start_ts=base_ts + i)

        rows = await svc.get_recent_errors(since_ts=base_ts - 1.0, limit=10)
        assert len(rows) == 10
        # Top 10 should be ts 24,23,22,21,20 (jobs) and ts 19,18,17,16,15 (handlers)
        ts_values = [r.execution_start_ts for r in rows]
        assert ts_values == sorted(ts_values, reverse=True)
        assert ts_values[0] == pytest.approx(base_ts + 24.0)
        # All 5 jobs in top 10
        job_rows = [r for r in rows if isinstance(r, JobErrorRecord)]
        assert len(job_rows) == 5

    async def test_get_recent_errors_left_join_orphans(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Delete a listener; its error records still appear with null app_key."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, handler_method="on_orphan")
        base_ts = 4_000_000.0
        await _insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 1.0)
        # Delete the listener (FK becomes NULL via ON DELETE SET NULL)
        await db_svc.db.execute("DELETE FROM listeners WHERE id = ?", (listener_id,))
        await db_svc.db.commit()

        rows = await svc.get_recent_errors(since_ts=base_ts)
        handler_rows = [r for r in rows if isinstance(r, HandlerErrorRecord)]
        assert len(handler_rows) == 1
        # Orphaned row: app_key and handler_method should be None
        assert handler_rows[0].app_key is None
        assert handler_rows[0].handler_method is None

    async def test_get_recent_errors_source_tier_filter_app(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' (default) excludes framework-tier errors."""
        db_svc, session_id = db
        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")
        app_job = await _insert_job(db_svc, job_name="app_job", source_tier="app")
        fw_job = await _insert_job(db_svc, job_name="fw_job", source_tier="framework")

        base_ts = 5_000_000.0
        await _insert_invocation(
            db_svc, app_listener, session_id, status="error", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="error", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )
        await _insert_execution(
            db_svc, app_job, session_id, status="error", execution_start_ts=base_ts + 3.0, source_tier="app"
        )
        await _insert_execution(
            db_svc, fw_job, session_id, status="error", execution_start_ts=base_ts + 4.0, source_tier="framework"
        )

        # Default source_tier='app'
        rows = await svc.get_recent_errors(since_ts=base_ts)
        assert len(rows) == 2
        assert all(isinstance(r, HandlerErrorRecord | JobErrorRecord) for r in rows)

    async def test_get_recent_errors_source_tier_filter_all(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='all' includes both app and framework errors."""
        db_svc, session_id = db
        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        base_ts = 6_000_000.0
        await _insert_invocation(
            db_svc, app_listener, session_id, status="error", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="error", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )

        rows = await svc.get_recent_errors(since_ts=base_ts, source_tier="all")
        assert len(rows) == 2

    async def test_get_recent_errors_source_tier_filter_framework(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' returns only framework-tier errors."""
        db_svc, session_id = db
        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        base_ts = 7_000_000.0
        await _insert_invocation(
            db_svc, app_listener, session_id, status="error", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="error", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )

        rows = await svc.get_recent_errors(since_ts=base_ts, source_tier="framework")
        assert len(rows) == 1
        assert isinstance(rows[0], HandlerErrorRecord)


class TestGetAllAppSummariesSourceTier:
    async def test_get_all_app_summaries_excludes_hassette(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Framework actors (__hassette__) are excluded from get_all_app_summaries."""
        db_svc, session_id = db

        # App-tier listener
        app_listener = await _insert_listener(db_svc, app_key="my_app", handler_method="on_a", source_tier="app")
        # Framework-tier listener registered as __hassette__
        fw_listener = await _insert_listener(
            db_svc, app_key="__hassette__", handler_method="on_fw", source_tier="framework"
        )

        base_ts = 8_000_000.0
        await _insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="success", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )

        result = await svc.get_all_app_summaries()
        assert "__hassette__" not in result
        assert "my_app" in result

    async def test_get_all_app_summaries_activity_filtered_by_app_tier(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Framework invocations don't inflate app-tier counts in get_all_app_summaries."""
        db_svc, session_id = db

        # App-tier listener for "my_app"
        app_listener = await _insert_listener(db_svc, app_key="my_app", handler_method="on_a", source_tier="app")
        # Framework-tier listener for "my_app" (same app_key, different tier)
        fw_listener = await _insert_listener(db_svc, app_key="my_app", handler_method="on_fw", source_tier="framework")

        base_ts = 9_000_000.0
        # 1 app-tier invocation
        await _insert_invocation(
            db_svc, app_listener, session_id, status="success", execution_start_ts=base_ts + 1.0, source_tier="app"
        )
        # 2 framework-tier invocations — must NOT be counted in app summary
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="success", execution_start_ts=base_ts + 2.0, source_tier="framework"
        )
        await _insert_invocation(
            db_svc, fw_listener, session_id, status="error", execution_start_ts=base_ts + 3.0, source_tier="framework"
        )

        result = await svc.get_all_app_summaries()
        assert "my_app" in result
        summary = result["my_app"]
        # Only the 1 app-tier invocation should be counted
        assert summary.total_invocations == 1
        assert summary.total_errors == 0


class TestDiFailureFlag:
    async def test_di_failure_flag_query(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """is_di_failure=1 records are counted as di_failures in get_listener_summary."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, handler_method="on_di")

        # 2 DI failures (is_di_failure=1) and 1 regular error
        await _insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=1
        )
        await _insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=1
        )
        await _insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="ValueError", is_di_failure=0
        )

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.di_failures == 2
        assert row.failed == 3

    async def test_di_failure_flag_not_string_match(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Records with error_type LIKE 'Dependency%' but is_di_failure=0 are NOT counted."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, handler_method="on_test")

        # error_type looks like a DI error but flag is 0
        await _insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyError", is_di_failure=0
        )
        # Real DI failure with flag set
        await _insert_invocation(
            db_svc, listener_id, session_id, status="error", error_type="DependencyInjectionError", is_di_failure=1
        )

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        # Only the one with is_di_failure=1 should count
        assert row.di_failures == 1


class TestGetSlowHandlersLeftJoin:
    async def test_get_slow_handlers_left_join(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Delete a listener; its slow invocations still appear with null app_key."""
        db_svc, session_id = db
        listener_id = await _insert_listener(db_svc, handler_method="on_slow")

        await _insert_invocation(db_svc, listener_id, session_id, duration_ms=500.0)
        # Delete the listener
        await db_svc.db.execute("DELETE FROM listeners WHERE id = ?", (listener_id,))
        await db_svc.db.commit()

        rows = await svc.get_slow_handlers(threshold_ms=100.0)
        assert len(rows) == 1
        # Orphaned row: app_key should be None (LEFT JOIN with no match)
        assert rows[0].duration_ms == pytest.approx(500.0)

    async def test_get_slow_handlers_source_tier_filter(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' (default) excludes framework slow handlers."""
        db_svc, session_id = db
        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        await _insert_invocation(db_svc, app_listener, session_id, duration_ms=500.0, source_tier="app")
        await _insert_invocation(db_svc, fw_listener, session_id, duration_ms=1000.0, source_tier="framework")

        rows = await svc.get_slow_handlers(threshold_ms=100.0)
        assert len(rows) == 1
        assert rows[0].duration_ms == pytest.approx(500.0)


class TestGetGlobalSummarySourceTier:
    async def test_get_global_summary_filters_app_tier(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary with default source_tier='app' excludes framework records."""
        db_svc, session_id = db

        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")
        app_job = await _insert_job(db_svc, job_name="app_job", source_tier="app")
        fw_job = await _insert_job(db_svc, job_name="fw_job", source_tier="framework")

        await _insert_invocation(db_svc, app_listener, session_id, status="success", source_tier="app")
        await _insert_invocation(db_svc, app_listener, session_id, status="error", source_tier="app")
        await _insert_invocation(db_svc, fw_listener, session_id, status="success", source_tier="framework")
        await _insert_execution(db_svc, app_job, session_id, status="success", source_tier="app")
        await _insert_execution(db_svc, fw_job, session_id, status="success", source_tier="framework")

        result = await svc.get_global_summary()
        # Default source_tier='app' — only app invocations counted
        assert result.listeners.total_invocations == 2
        assert result.listeners.total_errors == 1
        assert result.jobs.total_executions == 1

    async def test_get_global_summary_all_tier_includes_framework(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary(source_tier='all') includes framework records."""
        db_svc, session_id = db

        app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        await _insert_invocation(db_svc, app_listener, session_id, status="success", source_tier="app")
        await _insert_invocation(db_svc, fw_listener, session_id, status="success", source_tier="framework")

        result = await svc.get_global_summary(source_tier="all")
        assert result.listeners.total_invocations == 2


# ---------------------------------------------------------------------------
# Tests: _source_tier_clause — uncovered branches (lines 44, 50-51)
# ---------------------------------------------------------------------------


class TestSourceTierClause:
    def test_invalid_alias_raises_value_error(self) -> None:
        """_source_tier_clause raises ValueError for an alias not in the allowed set."""
        from hassette.core.telemetry_query_service import _source_tier_clause

        with pytest.raises(ValueError, match="Unexpected SQL alias"):
            _source_tier_clause("app", "x")

    def test_framework_tier_returns_filter_fragment(self) -> None:
        """_source_tier_clause('framework', ...) returns an AND clause with 'framework' param."""
        from hassette.core.telemetry_query_service import _source_tier_clause

        fragment, params = _source_tier_clause("framework", "l")
        assert "source_tier" in fragment
        assert params == ["framework"]

    def test_all_tier_returns_empty(self) -> None:
        """_source_tier_clause('all', ...) returns an empty fragment and empty params."""
        from hassette.core.telemetry_query_service import _source_tier_clause

        fragment, params = _source_tier_clause("all", "hi")
        assert fragment == ""
        assert params == []

    def test_app_tier_returns_filter_fragment(self) -> None:
        """_source_tier_clause('app', ...) returns an AND clause with 'app' param."""
        from hassette.core.telemetry_query_service import _source_tier_clause

        fragment, params = _source_tier_clause("app", "je")
        assert "source_tier" in fragment
        assert params == ["app"]

    def test_all_valid_aliases_accepted(self) -> None:
        """All four valid aliases are accepted without raising."""
        from hassette.core.telemetry_query_service import _source_tier_clause

        for alias in ("l", "hi", "je", "sj"):
            # Should not raise
            _source_tier_clause("app", alias)


# ---------------------------------------------------------------------------
# Tests: get_job_summary with session_id — uncovered lines 175-176
# ---------------------------------------------------------------------------


class TestGetJobSummarySessionScoped:
    async def test_get_job_summary_session_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """session_id restricts job execution counts to a single session."""
        db_svc, session_a = db

        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        j1 = await _insert_job(db_svc, job_name="job_a")

        # Session A: 2 executions
        await _insert_execution(db_svc, j1, session_a, status="success", duration_ms=10.0)
        await _insert_execution(db_svc, j1, session_a, status="error", duration_ms=20.0)
        # Session B: 1 execution (should NOT be counted)
        await _insert_execution(db_svc, j1, session_b, status="success", duration_ms=30.0)

        rows = await svc.get_job_summary("test_app", 0, session_id=session_a)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_executions == 2
        assert row.successful == 1
        assert row.failed == 1


# ---------------------------------------------------------------------------
# Tests: get_all_app_summaries with source_tier='framework' (lines 237-244)
# ---------------------------------------------------------------------------


class TestGetAllAppSummariesFrameworkTier:
    async def test_get_all_app_summaries_framework_tier(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' selects active_framework_listeners and active_framework_scheduled_jobs."""
        db_svc, session_id = db

        # Framework-tier listener and job under __hassette__
        fw_listener = await _insert_listener(
            db_svc, app_key="__hassette__", handler_method="on_fw", source_tier="framework"
        )
        fw_job = await _insert_job(db_svc, app_key="__hassette__", job_name="fw_job", source_tier="framework")

        # App-tier listener and job (should NOT appear for framework query)
        _app_listener = await _insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")
        _app_job = await _insert_job(db_svc, app_key="my_app", job_name="app_job", source_tier="app")

        await _insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )
        await _insert_execution(db_svc, fw_job, session_id, status="success", duration_ms=10.0, source_tier="framework")

        result = await svc.get_all_app_summaries(source_tier="framework")

        # Framework data lives under __hassette__ key, which is discarded by FRAMEWORK_APP_KEY guard
        # So result should be empty (the __hassette__ key is excluded)
        assert "my_app" not in result

    async def test_get_all_app_summaries_framework_tier_non_hassette_app_key(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='framework' shows framework-tier records for non-__hassette__ app_key."""
        db_svc, session_id = db

        # A regular app with mixed-tier listeners
        fw_listener = await _insert_listener(db_svc, app_key="my_app", handler_method="on_fw", source_tier="framework")
        await _insert_listener(db_svc, app_key="my_app", handler_method="on_app", source_tier="app")

        await _insert_invocation(
            db_svc, fw_listener, session_id, status="success", duration_ms=5.0, source_tier="framework"
        )

        result = await svc.get_all_app_summaries(source_tier="framework")
        # my_app has 1 framework-tier listener (instance 0)
        assert "my_app" in result
        summary = result["my_app"]
        assert summary.handler_count == 1  # only the framework listener
        assert summary.total_invocations == 1


# ---------------------------------------------------------------------------
# Tests: get_global_summary with source_tier='framework' (lines 406-412, 415-437)
# ---------------------------------------------------------------------------


class TestGetGlobalSummaryFrameworkTier:
    async def test_get_global_summary_framework_tier_no_session(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary(source_tier='framework') uses active_framework_listeners/jobs views."""
        db_svc, session_id = db

        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")
        fw_job = await _insert_job(db_svc, job_name="fw_job", source_tier="framework")
        _app_listener = await _insert_listener(db_svc, handler_method="on_app", source_tier="app")
        _app_job = await _insert_job(db_svc, job_name="app_job", source_tier="app")

        await _insert_invocation(db_svc, fw_listener, session_id, status="success", source_tier="framework")
        await _insert_invocation(db_svc, fw_listener, session_id, status="error", source_tier="framework")
        # App-tier invocations must not count
        await _insert_invocation(db_svc, _app_listener, session_id, status="success", source_tier="app")
        await _insert_execution(db_svc, fw_job, session_id, status="success", source_tier="framework")
        # App-tier execution must not count
        await _insert_execution(db_svc, _app_job, session_id, status="success", source_tier="app")

        result = await svc.get_global_summary(source_tier="framework")
        assert isinstance(result, GlobalSummary)
        # Only framework-tier counts
        assert result.listeners.total_invocations == 2
        assert result.listeners.total_errors == 1
        assert result.jobs.total_executions == 1
        # total_listeners and total_jobs from framework views only
        assert result.listeners.total_listeners == 1
        assert result.jobs.total_jobs == 1

    async def test_get_global_summary_framework_tier_with_session(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_global_summary(source_tier='framework', session_id=...) uses WHERE session_id + framework filter."""
        db_svc, session_a = db

        cursor = await db_svc.db.execute(
            "INSERT INTO sessions (started_at, last_heartbeat_at, status) VALUES (?, ?, 'stopped')",
            (time.time(), time.time()),
        )
        session_b = cursor.lastrowid
        await db_svc.db.commit()

        fw_listener = await _insert_listener(db_svc, handler_method="on_fw", source_tier="framework")

        # Session A: 2 framework invocations
        await _insert_invocation(db_svc, fw_listener, session_a, status="success", source_tier="framework")
        await _insert_invocation(db_svc, fw_listener, session_a, status="error", source_tier="framework")
        # Session B: 1 framework invocation (must NOT count)
        await _insert_invocation(db_svc, fw_listener, session_b, status="success", source_tier="framework")

        result = await svc.get_global_summary(source_tier="framework", session_id=session_a)
        assert result.listeners.total_invocations == 2
        assert result.listeners.total_errors == 1


# ---------------------------------------------------------------------------
# Tests: check_health (lines 713-714)
# ---------------------------------------------------------------------------


class TestCheckHealth:
    async def test_check_health_succeeds_on_live_db(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """check_health() completes without raising when the database is live."""
        # Should not raise
        await svc.check_health()

    async def test_check_health_raises_on_closed_db(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """check_health() raises when the read_db connection is closed."""
        import aiosqlite

        db_svc, _session_id = db
        # Close the read connection to simulate a failed connection
        await db_svc._read_db.close()
        try:
            with pytest.raises((sqlite3.Error, ValueError)):
                await svc.check_health()
        finally:
            # Restore so fixture teardown doesn't crash
            db_svc._read_db = await aiosqlite.connect(db_svc._db_path, isolation_level=None)
            db_svc._read_db.row_factory = aiosqlite.Row
