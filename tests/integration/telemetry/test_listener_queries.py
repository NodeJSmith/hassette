"""Integration tests for TelemetryQueryService.get_listener_summary()."""

import pytest

from hassette.core.telemetry.query_service import TelemetryQueryService
from hassette.schemas.listener_models import ListenerSummary

from .helpers import (
    BASE_TS,
    SINCE_WINDOW_ERROR_ROWS,
    DbFixture,
    assert_last_error_row_coherence,
    assert_no_last_error,
    error_row,
    insert_invocation,
    insert_listener,
    only_row,
)


class TestGetListenerSummary:
    async def test_get_listener_summary_aggregates(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """2 listeners, 3 invocations (2 success, 1 error) — correct aggregates."""
        db_svc, session_id = db

        listener_id_1 = await insert_listener(db_svc, handler_method="on_a")
        _listener_id_2 = await insert_listener(db_svc, handler_method="on_b")

        await insert_invocation(db_svc, listener_id_1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, listener_id_1, session_id, status="success", duration_ms=20.0)
        await insert_invocation(
            db_svc, listener_id_1, session_id, status="error", duration_ms=5.0, error_type="ValueError"
        )

        rows = await query_service.get_listener_summary("test_app", 0)
        assert len(rows) == 2

        assert all(isinstance(r, ListenerSummary) for r in rows)
        row = next(r for r in rows if r.handler_method == "on_a")
        assert row.total_invocations == 3
        assert row.successful == 2
        assert row.failed == 1
        assert row.avg_duration_ms == pytest.approx((10.0 + 20.0 + 5.0) / 3)

    async def test_get_listener_summary_empty(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """1 listener with no invocations — appears in results with zero counts."""
        db_svc, _session_id = db
        await insert_listener(db_svc, handler_method="on_idle")

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert row.total_invocations == 0
        assert row.successful == 0
        assert row.failed == 0

    async def test_get_listener_summary_excludes_cancelled(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """get_listener_summary excludes listeners with removed_at set (replace/cancel)."""
        db_svc, _session_id = db
        live = await insert_listener(db_svc, handler_method="on_live")
        cancelled = await insert_listener(db_svc, handler_method="on_cancelled")
        await db_svc.db.execute("UPDATE listeners SET removed_at = ? WHERE id = ?", (BASE_TS, cancelled))
        await db_svc.db.commit()

        scoped = await query_service.get_listener_summary("test_app", 0)
        assert {r.listener_id for r in scoped} == {live}

    async def test_get_listener_summary_global_excludes_cancelled(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """get_listener_summary(app_key=None) excludes listeners with removed_at set."""
        db_svc, _session_id = db
        live = await insert_listener(db_svc, handler_method="on_live")
        cancelled = await insert_listener(db_svc, handler_method="on_cancelled")
        await db_svc.db.execute("UPDATE listeners SET removed_at = ? WHERE id = ?", (BASE_TS, cancelled))
        await db_svc.db.commit()

        all_rows = await query_service.get_listener_summary()
        assert {r.listener_id for r in all_rows} == {live}

    async def test_get_listener_summary_since_scoped(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
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

        row = await only_row(query_service.get_listener_summary("test_app", 0, since=since_ts))
        assert row.total_invocations == 2
        assert row.successful == 2
        assert row.failed == 0

    async def test_get_listener_summary_min_max_none_when_no_invocations(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Handler with no invocations returns None for min_duration_ms and max_duration_ms."""
        db_svc, _session_id = db
        await insert_listener(db_svc, handler_method="on_idle")

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert row.min_duration_ms is None
        assert row.max_duration_ms is None

    async def test_get_listener_summary_min_max_correct_with_invocations(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Handler with invocations returns correct min and max duration."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_varied")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=15.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=5.0)
        await insert_invocation(db_svc, listener_id, session_id, status="error", duration_ms=100.0)

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert row.min_duration_ms == pytest.approx(5.0)
        assert row.max_duration_ms == pytest.approx(100.0)

    async def test_get_listener_summary_last_error_traceback_populated(
        self, query_service: TelemetryQueryService, db: DbFixture
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

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert (
            row.last_error_traceback == "Traceback (most recent call last):\n  File test.py, line 42\nValueError: oops"
        )
        assert row.last_error_type == "ValueError"

    async def test_get_listener_summary_last_error_traceback_none_when_no_errors(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Handler with no errors has None for last_error_traceback."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_clean")

        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, listener_id, session_id, status="success", duration_ms=20.0)

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert row.last_error_traceback is None


class TestListenerSummaryLastErrorRowCoherence:
    """Verify that last_error_* fields all come from the same invocation row (row coherence)."""

    async def test_multiple_errors_returns_most_recent(
        self, query_service: TelemetryQueryService, db: DbFixture
    ) -> None:
        """Multiple errors at different timestamps — all three error columns come from the most recent row."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_err")

        base_ts = BASE_TS

        await assert_last_error_row_coherence(
            lambda **kw: insert_invocation(db_svc, listener_id, session_id, **kw),
            lambda: query_service.get_listener_summary("test_app", 0),
            [
                error_row("OldError", "old message", "old traceback", base_ts + 1.0),
                error_row("MiddleError", "middle message", "middle traceback", base_ts + 5.0),
                error_row("NewError", "new message", "new traceback", base_ts + 10.0),
            ],
            trailing_success_ts=base_ts + 15.0,
        )

    async def test_single_error_returned(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
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

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert row.last_error_type == "ValueError"
        assert row.last_error_message == "bad value"
        assert row.last_error_traceback == "tb line 1\ntb line 2"

    async def test_no_errors_returns_none(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """No errors — all last_error_* fields are None."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_clean")

        await insert_invocation(db_svc, listener_id, session_id, status="success")
        await insert_invocation(db_svc, listener_id, session_id, status="success")

        row = await only_row(query_service.get_listener_summary("test_app", 0))
        assert_no_last_error(row)

    async def test_since_filter_scopes_error_cte(self, query_service: TelemetryQueryService, db: DbFixture) -> None:
        """Error before the since window is excluded; error inside the window is returned."""
        db_svc, session_id = db
        listener_id = await insert_listener(db_svc, handler_method="on_windowed")

        base_ts = BASE_TS
        since_ts = base_ts + 50.0

        await assert_last_error_row_coherence(
            lambda **kw: insert_invocation(db_svc, listener_id, session_id, **kw),
            lambda: query_service.get_listener_summary("test_app", 0, since=since_ts),
            SINCE_WINDOW_ERROR_ROWS,
        )

    async def test_since_filter_excludes_all_errors_returns_none(
        self, query_service: TelemetryQueryService, db: DbFixture
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

        row = await only_row(query_service.get_listener_summary("test_app", 0, since=since_ts))
        assert_no_last_error(row)
