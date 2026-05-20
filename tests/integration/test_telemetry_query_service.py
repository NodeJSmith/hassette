"""Integration tests for TelemetryQueryService with real SQLite database."""

import time

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry_models import (
    HandlerInvocation,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionRecord,
)
from hassette.core.telemetry_query_service import TelemetryQueryService

from .telemetry_query_helpers import (
    BASE_TS,
    db,  # noqa: F401 (pytest fixture)
    db_hassette,  # noqa: F401 (pytest fixture)
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
    svc,  # noqa: F401 (pytest fixture)
)


class TestGetListenerSummary:
    async def test_get_listener_summary_aggregates(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 listeners, 3 invocations (2 success, 1 error) — correct aggregates."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, handler_method="on_a")
        _l2 = await insert_listener(db_svc, handler_method="on_b")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=20.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=5.0, error_type="ValueError")

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
        await insert_listener(db_svc, handler_method="on_idle")

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 0
        assert row.successful == 0
        assert row.failed == 0

    async def test_get_listener_summary_since_scoped(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 invocations after since, 1 before — since filter returns only the 2 recent ones."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 5.0

        listener_id = await insert_listener(db_svc, handler_method="on_event")
        # Two invocations after since_ts — should count
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 10.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", execution_start_ts=base_ts + 20.0)
        # One invocation before since_ts — should NOT count
        await insert_invocation(db_svc, listener_id, session_id, status="error", execution_start_ts=base_ts + 1.0)

        rows = await svc.get_listener_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 2
        assert row.successful == 2
        assert row.failed == 0

    async def test_get_listener_summary_min_max_none_when_no_invocations(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with no invocations returns None for min_duration_ms and max_duration_ms."""
        db_svc, _session_id = db
        await insert_listener(db_svc, handler_method="on_idle")

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_listener_summary_min_max_correct_with_invocations(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with invocations returns correct min and max duration."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_varied")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=15.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=5.0)
        await insert_invocation(db_svc, listener_id, session_id, status="error", duration_ms=100.0)

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms == pytest.approx(5.0)
        assert row.max_duration_ms == pytest.approx(100.0)

    async def test_get_listener_summary_last_error_traceback_populated(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with errors includes last_error_traceback from the most recent error."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_err")

        base_ts = BASE_TS
        # Older error — not the most recent
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="OldError",
            error_message="old message",
            error_traceback="old traceback\n  at old.py:1",
            execution_start_ts=base_ts + 1.0,
        )
        # Most recent error — traceback should be returned
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="ValueError",
            error_message="latest message",
            error_traceback="Traceback (most recent call last):\n  File test.py, line 42\nValueError: oops",
            execution_start_ts=base_ts + 10.0,
        )

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert (
            row.last_error_traceback == "Traceback (most recent call last):\n  File test.py, line 42\nValueError: oops"
        )
        assert row.last_error_type == "ValueError"

    async def test_get_listener_summary_last_error_traceback_none_when_no_errors(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with no errors has None for last_error_traceback."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_clean")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=20.0)

        rows = await svc.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_traceback is None


class TestGetJobSummary:
    async def test_get_job_summary_aggregates(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 jobs, mixed results — correct aggregate totals."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, job_name="job_a")
        j2 = await insert_job(db_svc, job_name="job_b")

        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)
        await insert_execution(db_svc, j2, session_id, status="success", duration_ms=200.0)

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

    async def test_get_job_summary_error_fields_populated_when_error_exists(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with at least one error execution returns last_error_message, last_error_type, last_error_ts."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="failing_job")

        base_ts = BASE_TS
        # Older error — not the most recent
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            duration_ms=30.0,
            error_type="OldError",
            error_message="old failure",
            execution_start_ts=base_ts + 1.0,
        )
        # Most recent error — should be returned
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            duration_ms=40.0,
            error_type="ValueError",
            error_message="something went wrong",
            execution_start_ts=base_ts + 10.0,
        )

        rows = await svc.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "ValueError"
        assert row.last_error_message == "something went wrong"
        assert row.last_error_ts == pytest.approx(base_ts + 10.0)

    async def test_get_job_summary_error_fields_none_when_only_successes(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with only successful executions has None for all error fields."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="clean_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=10.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=20.0)

        rows = await svc.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_ts is None

    async def test_get_job_summary_error_fields_none_when_no_executions(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with no executions has None for all error fields AND duration fields."""
        db_svc, _session_id = db

        await insert_job(db_svc, job_name="idle_job")

        rows = await svc.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_ts is None
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_job_summary_min_max_duration_correct(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with multiple executions at different durations returns correct min and max."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="varied_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=50.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=200.0)
        await insert_execution(db_svc, job_id, session_id, status="error", duration_ms=10.0)

        rows = await svc.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms == pytest.approx(10.0)
        assert row.max_duration_ms == pytest.approx(200.0)
        assert row.avg_duration_ms == pytest.approx((50.0 + 200.0 + 10.0) / 3)

    async def test_get_job_summary_last_error_picks_up_timed_out(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A timed-out execution is surfaced as the last error."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="timeout_job")
        base_ts = BASE_TS
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="timed_out",
            duration_ms=30_000.0,
            error_type="TimeoutError",
            error_message="exceeded limit",
            execution_start_ts=base_ts + 5.0,
        )

        rows = await svc.get_job_summary("test_app", 0)
        row = rows[0]
        assert row.last_error_type == "TimeoutError"
        assert row.last_error_message == "exceeded limit"
        assert row.last_error_ts == pytest.approx(base_ts + 5.0)

    async def test_get_job_summary_last_error_none_when_error_predates_since(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error outside the since window returns None for error fields."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="old_error_job")
        base_ts = BASE_TS
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            duration_ms=10.0,
            error_type="OldError",
            error_message="ancient failure",
            execution_start_ts=base_ts + 1.0,
        )

        rows = await svc.get_job_summary("test_app", 0, since=base_ts + 50.0)
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_ts is None


class TestGetHandlerInvocations:
    async def test_get_handler_invocations_ordered(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """5 invocations at different timestamps — most recent first, limit respected."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)

        base_ts = time.time()
        for i in range(5):
            await insert_invocation(db_svc, listener_id, session_id, execution_start_ts=base_ts + i)

        # limit=3 returns 3 most recent
        rows = await svc.get_handler_invocations(listener_id, limit=3)
        assert len(rows) == 3
        assert all(isinstance(r, HandlerInvocation) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 4)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 3)
        assert rows[2].execution_start_ts == pytest.approx(base_ts + 2)


class TestGetJobExecutions:
    async def test_get_job_executions_ordered(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """3 executions — ordered DESC, respects limit."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc)

        base_ts = time.time()
        for i in range(3):
            await insert_execution(db_svc, job_id, session_id, execution_start_ts=base_ts + i)

        rows = await svc.get_job_executions(job_id, limit=2)
        assert len(rows) == 2
        assert all(isinstance(r, JobExecution) for r in rows)
        assert rows[0].execution_start_ts == pytest.approx(base_ts + 2)
        assert rows[1].execution_start_ts == pytest.approx(base_ts + 1)


class TestGetSlowHandlers:
    async def test_get_slow_handlers(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Mix of fast + slow invocations — only above threshold returned, ordered by duration."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc)

        await insert_invocation(db_svc, listener_id, session_id, duration_ms=5.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=100.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=500.0)
        await insert_invocation(db_svc, listener_id, session_id, duration_ms=50.0)

        rows = await svc.get_slow_handlers(threshold_ms=60.0)
        assert len(rows) == 2
        assert rows[0].duration_ms == pytest.approx(500.0)
        assert rows[1].duration_ms == pytest.approx(100.0)


class TestGetSessionList:
    async def test_get_session_list(
        self,
        svc: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """3 sessions with different statuses — ordered by started_at DESC, correct duration."""
        db_svc, session_id = db

        base_ts = BASE_TS

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
