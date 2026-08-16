"""Integration tests for TelemetryQueryService.get_job_summary()."""

import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.job_models import JobSummary

from .helpers import (
    BASE_TS,
    SINCE_WINDOW_ERROR_ROWS,
    DbFixture,
    assert_last_error_row_coherence,
    assert_no_last_error,
    error_row,
    insert_execution,
    insert_job,
    only_row,
)


class TestGetJobSummary:
    async def test_get_job_summary_aggregates(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """2 jobs, mixed results — correct aggregate totals."""
        db_svc, session_id = db

        job_id_1 = await insert_job(db_svc, job_name="job_a")
        job_id_2 = await insert_job(db_svc, job_name="job_b")

        await insert_execution(db_svc, job_id_1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, job_id_1, session_id, status="error", duration_ms=50.0)
        await insert_execution(db_svc, job_id_2, session_id, status="success", duration_ms=200.0)

        rows = await query_service.get_job_summary("test_app", 0)
        assert len(rows) == 2

        assert all(isinstance(r, JobSummary) for r in rows)
        row1 = next(r for r in rows if r.job_name == "job_a")
        assert row1.job_id == job_id_1
        assert row1.app_key == "test_app"
        assert row1.instance_index == 0
        assert row1.total_executions == 2
        assert row1.successful == 1
        assert row1.failed == 1
        assert row1.avg_duration_ms == pytest.approx(75.0)

        row2 = next(r for r in rows if r.job_name == "job_b")
        assert row2.job_id == job_id_2
        assert row2.total_executions == 1
        assert row2.successful == 1
        assert row2.failed == 0

    async def test_get_job_summary_error_fields_populated_when_error_exists(
        self, query_service: TelemetryQueryService, db: DbFixture
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

        row = await only_row(query_service.get_job_summary("test_app", 0))
        assert row.last_error_type == "ValueError"
        assert row.last_error_message == "something went wrong"
        assert row.last_error_ts == pytest.approx(base_ts + 10.0)

    async def test_get_job_summary_error_fields_none_when_only_successes(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """A job with only successful executions has None for all error fields."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="clean_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=10.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=20.0)

        row = await only_row(query_service.get_job_summary("test_app", 0))
        assert_no_last_error(row)

    async def test_get_job_summary_error_fields_none_when_no_executions(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """A job with no executions has None for all error fields AND duration fields."""
        db_svc, _session_id = db

        await insert_job(db_svc, job_name="idle_job")

        row = await only_row(query_service.get_job_summary("test_app", 0))
        assert_no_last_error(row)
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_job_summary_min_max_duration_correct(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """A job with multiple executions at different durations returns correct min and max."""
        db_svc, session_id = db

        job_id = await insert_job(db_svc, job_name="varied_job")
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=50.0)
        await insert_execution(db_svc, job_id, session_id, status="success", duration_ms=200.0)
        await insert_execution(db_svc, job_id, session_id, status="error", duration_ms=10.0)

        row = await only_row(query_service.get_job_summary("test_app", 0))
        assert row.min_duration_ms == pytest.approx(10.0)
        assert row.max_duration_ms == pytest.approx(200.0)
        assert row.avg_duration_ms == pytest.approx((50.0 + 200.0 + 10.0) / 3)

    async def test_get_job_summary_last_error_picks_up_timed_out(
        self, query_service: TelemetryQueryService, db: DbFixture
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
        self, query_service: TelemetryQueryService, db: DbFixture
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
        assert_no_last_error(row)


class TestGetJobSummarySinceScoped:
    async def test_get_job_summary_since_scoped(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Since filter restricts job execution counts to records after the threshold."""
        db_svc, session_id = db

        base_ts = BASE_TS
        since_ts = base_ts + 5.0

        j1 = await insert_job(db_svc, job_name="job_a")

        # 2 executions after since_ts — should count
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=10.0, execution_start_ts=base_ts + 10.0
        )
        await insert_execution(
            db_svc, j1, session_id, status="error", duration_ms=20.0, execution_start_ts=base_ts + 20.0
        )
        # 1 execution before since_ts — should NOT be counted
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=30.0, execution_start_ts=base_ts + 1.0
        )

        row = await only_row(query_service.get_job_summary("test_app", 0, since=since_ts))
        assert row.total_executions == 2
        assert row.successful == 1
        assert row.failed == 1


class TestJobSummaryLastErrorRowCoherence:
    """Verify that last_error_* fields all come from the same job_executions row."""

    async def test_multiple_errors_returns_most_recent(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Multiple errors at different timestamps — all error columns from the most recent row."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="multi_err_job")

        base_ts = BASE_TS

        await assert_last_error_row_coherence(
            lambda **kw: insert_execution(db_svc, job_id, session_id, **kw),
            lambda: query_service.get_job_summary("test_app", 0),
            [
                error_row("OldError", "old message", "old traceback", base_ts + 1.0),
                error_row("NewError", "new message", "new traceback", base_ts + 10.0),
            ],
            trailing_success_ts=base_ts + 20.0,
        )

    async def test_single_error_returned(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Single error execution — all error columns are populated from that row."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="single_err_job")

        await assert_last_error_row_coherence(
            lambda **kw: insert_execution(db_svc, job_id, session_id, **kw),
            lambda: query_service.get_job_summary("test_app", 0),
            [
                error_row("RuntimeError", "runtime boom", "tb: boom at line 1", BASE_TS + 5.0),
            ],
        )

    async def test_no_errors_returns_none(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """No errors — all last_error_* fields are None."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="clean_job")

        await insert_execution(db_svc, job_id, session_id, status="success")
        await insert_execution(db_svc, job_id, session_id, status="success")

        row = await only_row(query_service.get_job_summary("test_app", 0))
        assert_no_last_error(row)

    async def test_since_filter_scopes_error_cte(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Error before the since window is excluded; error inside the window is returned."""
        db_svc, session_id = db
        job_id = await insert_job(db_svc, job_name="windowed_job")

        base_ts = BASE_TS
        since_ts = base_ts + 50.0

        await assert_last_error_row_coherence(
            lambda **kw: insert_execution(db_svc, job_id, session_id, **kw),
            lambda: query_service.get_job_summary("test_app", 0, since=since_ts),
            SINCE_WINDOW_ERROR_ROWS,
        )

    async def test_since_filter_excludes_all_errors_returns_none(
        self, query_service: TelemetryQueryService, db: DbFixture
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

        row = await only_row(query_service.get_job_summary("test_app", 0, since=since_ts))
        assert_no_last_error(row)
