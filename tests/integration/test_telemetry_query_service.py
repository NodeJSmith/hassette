"""Integration tests for TelemetryQueryService with real SQLite database."""

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerInvocation,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionSummary,
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
    hassette.config.database_service_log_level = "INFO"
    hassette.config.log_level = "INFO"
    hassette.config.task_bucket_log_level = "INFO"
    hassette.config.resource_shutdown_timeout_seconds = 5
    hassette.config.task_cancellation_timeout_seconds = 5
    hassette.config.web_api_log_level = "INFO"
    hassette.config.run_web_api = True
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
) -> int:
    """Insert a listener row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO listeners
               (app_key, instance_index, handler_method, topic,
                debounce, throttle, once, priority,
                source_location,
                first_registered_at, last_registered_at)
           VALUES (?, ?, ?, ?, NULL, NULL, 0, 0, 'test.py:1', ?, ?)""",
        (app_key, instance_index, handler_method, topic, time.time(), time.time()),
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
) -> int:
    """Insert a scheduled_job row and return its id."""
    cursor = await db_svc.db.execute(
        """INSERT INTO scheduled_jobs
               (app_key, instance_index, job_name, handler_method,
                trigger_type, trigger_value, repeat,
                source_location,
                first_registered_at, last_registered_at)
           VALUES (?, ?, ?, ?, 'interval', '60', 1, 'test.py:1', ?, ?)""",
        (app_key, instance_index, job_name, handler_method, time.time(), time.time()),
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
) -> int:
    """Insert a handler_invocations row and return its id."""
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO handler_invocations
               (listener_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (listener_id, session_id, ts, duration_ms, status, error_type, error_message),
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
) -> int:
    """Insert a job_executions row and return its id."""
    ts = execution_start_ts if execution_start_ts is not None else time.time()
    cursor = await db_svc.db.execute(
        """INSERT INTO job_executions
               (job_id, session_id, execution_start_ts, duration_ms,
                status, error_type, error_message)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (job_id, session_id, ts, duration_ms, status, error_type, error_message),
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
        kinds = {r["kind"] for r in rows}
        assert "handler" in kinds
        assert "job" in kinds

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
        assert rows[0]["kind"] == "handler"


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
        assert rows[0]["duration_ms"] == pytest.approx(500.0)
        assert rows[1]["duration_ms"] == pytest.approx(100.0)


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

        # Most recent first: started_at DESC
        assert rows[0]["started_at"] == pytest.approx(base_ts + 200.0)
        assert rows[1]["started_at"] == pytest.approx(base_ts + 100.0)
        assert rows[2]["started_at"] == pytest.approx(base_ts + 0.0)

        # duration_seconds for stopped sessions = stopped_at - started_at
        assert rows[1]["duration_seconds"] == pytest.approx(50.0)
        assert rows[2]["duration_seconds"] == pytest.approx(50.0)

        # Running session uses last_heartbeat_at for duration
        assert rows[0]["duration_seconds"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Tests: get_current_session_summary
# ---------------------------------------------------------------------------


class TestGetCurrentSessionSummary:
    async def test_get_current_session_summary_running(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """1 running session with invocations — correct invocation/execution counts."""
        db_svc, session_id = db

        listener_id = await _insert_listener(db_svc)
        job_id = await _insert_job(db_svc)

        await _insert_invocation(db_svc, listener_id, session_id, status="success")
        await _insert_invocation(db_svc, listener_id, session_id, status="error")
        await _insert_execution(db_svc, job_id, session_id, status="success")
        await _insert_execution(db_svc, job_id, session_id, status="error")

        result = await svc.get_current_session_summary()
        assert isinstance(result, SessionSummary)
        assert result.total_invocations == 2
        assert result.invocation_errors == 1
        assert result.total_executions == 2
        assert result.execution_errors == 1

    async def test_get_current_session_summary_no_session(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """No running session — returns None."""
        db_svc, session_id = db

        # Mark the session as stopped
        await db_svc.db.execute("UPDATE sessions SET status = 'stopped' WHERE id = ?", (session_id,))
        await db_svc.db.commit()

        result = await svc.get_current_session_summary()
        assert result is None


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
# Tests: get_current_session_summary returns typed model
# ---------------------------------------------------------------------------


class TestGetCurrentSessionSummaryTyped:
    async def test_get_current_session_summary_returns_typed_model(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_current_session_summary returns SessionSummary, not dict."""
        db_svc, session_id = db

        l1 = await _insert_listener(db_svc)
        j1 = await _insert_job(db_svc)
        await _insert_invocation(db_svc, l1, session_id, status="success")
        await _insert_execution(db_svc, j1, session_id, status="error")

        result = await svc.get_current_session_summary()
        assert isinstance(result, SessionSummary)
        assert result.total_invocations == 1
        assert result.invocation_errors == 0
        assert result.total_executions == 1
        assert result.execution_errors == 1
