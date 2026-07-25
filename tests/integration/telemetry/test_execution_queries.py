"""Integration tests for execution-level queries.

Covers get_executions(), get_slow_handlers(), and last_error_* row coherence
for both listener and job summaries.
"""

import time

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.execution_models import Execution

from .helpers import BASE_TS, insert_execution, insert_invocation, insert_job, insert_listener


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
