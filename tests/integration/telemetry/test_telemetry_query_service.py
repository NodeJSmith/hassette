"""Integration tests for TelemetryQueryService with real SQLite database."""

import time

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.telemetry_models import (
    Execution,
    JobSummary,
    ListenerSummary,
    SessionRecord,
)

from .helpers import (
    BASE_TS,
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
)


class TestGetListenerSummary:
    async def test_get_listener_summary_aggregates(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 listeners, 3 invocations (2 success, 1 error) — correct aggregates."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, handler_method="on_a")
        _l2 = await insert_listener(db_svc, handler_method="on_b")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=20.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=5.0, error_type="ValueError")

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 2

        assert all(isinstance(r, ListenerSummary) for r in rows)
        row = next(r for r in rows if r.handler_method == "on_a")
        assert row.total_invocations == 3
        assert row.successful == 2
        assert row.failed == 1
        assert row.avg_duration_ms == pytest.approx((10.0 + 20.0 + 5.0) / 3)

    async def test_get_listener_summary_empty(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """1 listener with no invocations — appears in results with zero counts."""
        db_svc, _session_id = db
        await insert_listener(db_svc, handler_method="on_idle")

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 0
        assert row.successful == 0
        assert row.failed == 0

    async def test_get_listener_summary_excludes_cancelled(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_listener_summary excludes listeners with cancelled_at set (replace/cancel)."""
        db_svc, _session_id = db
        live = await insert_listener(db_svc, handler_method="on_live")
        cancelled = await insert_listener(db_svc, handler_method="on_cancelled")
        await db_svc.db.execute("UPDATE listeners SET cancelled_at = ? WHERE id = ?", (BASE_TS, cancelled))
        await db_svc.db.commit()

        scoped = await query_service.get_listener_summary("test_app", 0)
        assert {r.listener_id for r in scoped} == {live}

    async def test_get_listener_summary_global_excludes_cancelled(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """get_listener_summary(app_key=None) excludes listeners with cancelled_at set."""
        db_svc, _session_id = db
        live = await insert_listener(db_svc, handler_method="on_live")
        cancelled = await insert_listener(db_svc, handler_method="on_cancelled")
        await db_svc.db.execute("UPDATE listeners SET cancelled_at = ? WHERE id = ?", (BASE_TS, cancelled))
        await db_svc.db.commit()

        all_rows = await query_service.get_listener_summary()
        assert {r.listener_id for r in all_rows} == {live}

    async def test_get_listener_summary_since_scoped(
        self,
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_listener_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.total_invocations == 2
        assert row.successful == 2
        assert row.failed == 0

    async def test_get_listener_summary_min_max_none_when_no_invocations(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with no invocations returns None for min_duration_ms and max_duration_ms."""
        db_svc, _session_id = db
        await insert_listener(db_svc, handler_method="on_idle")

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_listener_summary_min_max_correct_with_invocations(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with invocations returns correct min and max duration."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_varied")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=15.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=5.0)
        await insert_invocation(db_svc, listener_id, session_id, status="error", duration_ms=100.0)

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms == pytest.approx(5.0)
        assert row.max_duration_ms == pytest.approx(100.0)

    async def test_get_listener_summary_last_error_traceback_populated(
        self,
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert (
            row.last_error_traceback == "Traceback (most recent call last):\n  File test.py, line 42\nValueError: oops"
        )
        assert row.last_error_type == "ValueError"

    async def test_get_listener_summary_last_error_traceback_none_when_no_errors(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Handler with no errors has None for last_error_traceback."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_clean")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=20.0)

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_traceback is None


class TestGetJobSummary:
    async def test_get_job_summary_aggregates(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """2 jobs, mixed results — correct aggregate totals."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, job_name="job_a")
        j2 = await insert_job(db_svc, job_name="job_b")

        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)
        await insert_execution(db_svc, j2, session_id, status="success", duration_ms=200.0)

        rows = await query_service.get_job_summary("test_app", 0)
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
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "ValueError"
        assert row.last_error_message == "something went wrong"
        assert row.last_error_ts == pytest.approx(base_ts + 10.0)

    async def test_get_job_summary_error_fields_none_when_only_successes(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with only successful executions has None for all error fields."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="clean_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=10.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=20.0)

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_ts is None

    async def test_get_job_summary_error_fields_none_when_no_executions(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with no executions has None for all error fields AND duration fields."""
        db_svc, _session_id = db

        await insert_job(db_svc, job_name="idle_job")

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_ts is None
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_job_summary_min_max_duration_correct(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A job with multiple executions at different durations returns correct min and max."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="varied_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=50.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=200.0)
        await insert_execution(db_svc, job_id, session_id, status="error", duration_ms=10.0)

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.min_duration_ms == pytest.approx(10.0)
        assert row.max_duration_ms == pytest.approx(200.0)
        assert row.avg_duration_ms == pytest.approx((50.0 + 200.0 + 10.0) / 3)

    async def test_get_job_summary_last_error_picks_up_timed_out(
        self,
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_job_summary("test_app", 0)
        row = rows[0]
        assert row.last_error_type == "TimeoutError"
        assert row.last_error_message == "exceeded limit"
        assert row.last_error_ts == pytest.approx(base_ts + 5.0)

    async def test_get_job_summary_last_error_none_when_error_predates_since(
        self,
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_job_summary("test_app", 0, since=base_ts + 50.0)
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_ts is None


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


class TestListenerSummaryLastErrorRowCoherence:
    """Verify that last_error_* fields all come from the same invocation row (row coherence)."""

    async def test_multiple_errors_returns_most_recent(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multiple errors at different timestamps — all three error columns come from the most recent row."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_err")

        base_ts = BASE_TS
        # Older error with distinct values
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="OldError",
            error_message="old message",
            error_traceback="old traceback",
            execution_start_ts=base_ts + 1.0,
        )
        # Middle error
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="MiddleError",
            error_message="middle message",
            error_traceback="middle traceback",
            execution_start_ts=base_ts + 5.0,
        )
        # Most recent error — all three columns should come from this row
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="NewError",
            error_message="new message",
            error_traceback="new traceback",
            execution_start_ts=base_ts + 10.0,
        )
        # A success after the errors — should not affect error fields
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="success",
            execution_start_ts=base_ts + 15.0,
        )

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        # All three error columns must come from the same (most recent) row
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "new message"
        assert row.last_error_traceback == "new traceback"

    async def test_single_error_returned(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Single error — all error columns are populated from that row."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_single_err")

        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="ValueError",
            error_message="bad value",
            error_traceback="tb line 1\ntb line 2",
            execution_start_ts=BASE_TS + 1.0,
        )

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "ValueError"
        assert row.last_error_message == "bad value"
        assert row.last_error_traceback == "tb line 1\ntb line 2"

    async def test_no_errors_returns_none(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """No errors — all last_error_* fields are None."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_clean")

        await insert_invocation(db_svc, listener_id, session_id, status="success")
        await insert_invocation(db_svc, listener_id, session_id, status="success")

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_traceback is None

    async def test_since_filter_scopes_error_cte(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error before the since window is excluded; error inside the window is returned."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_windowed")

        base_ts = BASE_TS
        since_ts = base_ts + 50.0

        # Error before the window — must be excluded
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="OldError",
            error_message="before window",
            error_traceback="old tb",
            execution_start_ts=base_ts + 1.0,
        )
        # Error inside the window — must be returned
        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="NewError",
            error_message="inside window",
            error_traceback="new tb",
            execution_start_ts=base_ts + 100.0,
        )

        rows = await query_service.get_listener_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "inside window"
        assert row.last_error_traceback == "new tb"

    async def test_since_filter_excludes_all_errors_returns_none(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All errors before since window — last_error_* fields are None."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_stale")

        base_ts = BASE_TS
        since_ts = base_ts + 500.0

        await insert_invocation(
            db_svc,
            listener_id,
            session_id,
            status="error",
            error_type="StaleError",
            error_message="before window",
            error_traceback="old tb",
            execution_start_ts=base_ts + 1.0,
        )

        rows = await query_service.get_listener_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_traceback is None


class TestJobSummaryLastErrorRowCoherence:
    """Verify that last_error_* fields all come from the same job_executions row."""

    async def test_multiple_errors_returns_most_recent(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multiple errors at different timestamps — all error columns from the most recent row."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="multi_err_job")

        base_ts = BASE_TS
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="OldError",
            error_message="old message",
            error_traceback="old traceback",
            execution_start_ts=base_ts + 1.0,
        )
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="NewError",
            error_message="new message",
            error_traceback="new traceback",
            execution_start_ts=base_ts + 10.0,
        )
        # Success after errors — should not affect error fields
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="success",
            execution_start_ts=base_ts + 20.0,
        )

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "new message"
        assert row.last_error_traceback == "new traceback"
        assert row.last_error_ts == pytest.approx(base_ts + 10.0)

    async def test_single_error_returned(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Single error execution — all error columns are populated from that row."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="single_err_job")

        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="RuntimeError",
            error_message="runtime boom",
            error_traceback="tb: boom at line 1",
            execution_start_ts=BASE_TS + 5.0,
        )

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "RuntimeError"
        assert row.last_error_message == "runtime boom"
        assert row.last_error_traceback == "tb: boom at line 1"

    async def test_no_errors_returns_none(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """No errors — all last_error_* fields are None."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="clean_job")

        await insert_execution(db_svc, job_id, session_id, status="success")
        await insert_execution(db_svc, job_id, session_id, status="success")

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_traceback is None
        assert row.last_error_ts is None

    async def test_since_filter_scopes_error_cte(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error before the since window is excluded; error inside the window is returned."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="windowed_job")

        base_ts = BASE_TS
        since_ts = base_ts + 50.0

        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="OldError",
            error_message="before window",
            error_traceback="old tb",
            execution_start_ts=base_ts + 1.0,
        )
        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="NewError",
            error_message="inside window",
            error_traceback="new tb",
            execution_start_ts=base_ts + 100.0,
        )

        rows = await query_service.get_job_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "inside window"
        assert row.last_error_traceback == "new tb"

    async def test_since_filter_excludes_all_errors_returns_none(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All errors before since window — last_error_* fields are None."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="stale_job")

        base_ts = BASE_TS
        since_ts = base_ts + 500.0

        await insert_execution(
            db_svc,
            job_id,
            session_id,
            status="error",
            error_type="StaleError",
            error_message="stale",
            error_traceback="stale tb",
            execution_start_ts=base_ts + 1.0,
        )

        rows = await query_service.get_job_summary("test_app", 0, since=since_ts)
        assert len(rows) == 1
        row = rows[0]
        assert row.last_error_type is None
        assert row.last_error_message is None
        assert row.last_error_traceback is None
        assert row.last_error_ts is None


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


class TestGetSessionList:
    async def test_get_session_list(
        self,
        query_service: TelemetryQueryService,
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

        rows = await query_service.get_session_list(limit=20)
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
