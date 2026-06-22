"""Tests for get_app_health_aggregates() and get_listener_summary().

Covers:
- get_app_health_aggregates() returns correct totals matching per-item sums
- get_app_health_aggregates() returns zero-values for apps with no invocations
- get_app_health_aggregates() respects the ``since`` parameter
- get_listener_summary() returns all listeners across multiple apps/instances
- get_listener_summary() last-error row coherence (ROW_NUMBER CTE)
- get_listener_summary() respects source_tier filtering
"""

import pytest

from hassette.core.database_service import DatabaseService
from hassette.core.telemetry.query_service import AppHealthAggregates, TelemetryQueryService
from hassette.schemas.telemetry_models import ListenerSummary

from .helpers import (
    BASE_TS,
    insert_execution,
    insert_invocation,
    insert_job,
    insert_listener,
)


class TestGetAppHealthAggregates:
    async def test_returns_correct_totals_matching_per_item_sums(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Totals from get_app_health_aggregates() match sum of per-listener/per-job detail queries."""
        db_svc, session_id = db

        # Two listeners with mixed statuses
        l1 = await insert_listener(db_svc, app_key="test_app", handler_method="on_a")
        l2 = await insert_listener(db_svc, app_key="test_app", handler_method="on_b")
        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=20.0)
        await insert_invocation(db_svc, l1, session_id, status="timed_out", duration_ms=5.0)
        await insert_invocation(db_svc, l2, session_id, status="success", duration_ms=30.0)

        # One job with mixed statuses
        j1 = await insert_job(db_svc, app_key="test_app", job_name="my_job")
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=100.0)
        await insert_execution(db_svc, j1, session_id, status="error", duration_ms=50.0)
        await insert_execution(db_svc, j1, session_id, status="timed_out", duration_ms=25.0)

        agg = await query_service.get_app_health_aggregates(app_key="test_app", instance_index=0)

        assert isinstance(agg, AppHealthAggregates)
        # Handler totals: 4 invocations across l1 and l2
        assert agg.total_invocations == 4
        assert agg.handler_errors == 1
        assert agg.handler_timed_out == 1
        # avg of (10 + 20 + 5 + 30) / 4 = 16.25
        assert agg.handler_avg_duration_ms == pytest.approx(16.25)

        # Job totals: 3 executions
        assert agg.total_executions == 3
        assert agg.job_errors == 1
        assert agg.job_timed_out == 1
        # avg of (100 + 50 + 25) / 3 = 58.33...
        assert agg.job_avg_duration_ms == pytest.approx(175.0 / 3.0)

        # last_activity_ts should be set (most recent invocation/execution)
        assert agg.last_activity_ts is not None

    async def test_excludes_cancelled_listener_invocations(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """A cancelled listener's invocations are excluded from handler aggregates."""
        db_svc, session_id = db

        live = await insert_listener(db_svc, app_key="test_app", handler_method="on_live")
        cancelled = await insert_listener(db_svc, app_key="test_app", handler_method="on_cancelled")
        await insert_invocation(db_svc, live, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, cancelled, session_id, status="error", duration_ms=20.0)
        await db_svc.db.execute("UPDATE listeners SET cancelled_at = ? WHERE id = ?", (1000.0, cancelled))
        await db_svc.db.commit()

        agg = await query_service.get_app_health_aggregates(app_key="test_app", instance_index=0)

        # Only the live listener's success counts; the cancelled listener's error is excluded.
        assert agg.total_invocations == 1
        assert agg.handler_errors == 0

    async def test_zero_invocations_returns_zero_values(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """App with no invocations or executions returns all-zero aggregates, None last_activity_ts."""
        result = await query_service.get_app_health_aggregates(app_key="no_such_app", instance_index=0)

        assert isinstance(result, AppHealthAggregates)
        assert result.total_invocations == 0
        assert result.handler_errors == 0
        assert result.handler_timed_out == 0
        assert result.handler_avg_duration_ms == 0.0
        assert result.total_executions == 0
        assert result.job_errors == 0
        assert result.job_timed_out == 0
        assert result.job_avg_duration_ms == 0.0
        assert result.last_activity_ts is None

    async def test_listeners_only_no_jobs(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """App with handlers but no jobs returns correct handler totals, zero job totals."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, app_key="handler_only", handler_method="on_event")
        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=15.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=8.0)

        agg = await query_service.get_app_health_aggregates(app_key="handler_only", instance_index=0)

        assert agg.total_invocations == 2
        assert agg.handler_errors == 1
        assert agg.handler_timed_out == 0
        assert agg.handler_avg_duration_ms == pytest.approx(11.5)
        assert agg.total_executions == 0
        assert agg.job_errors == 0
        assert agg.job_avg_duration_ms == 0.0

    async def test_jobs_only_no_listeners(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """App with jobs but no listeners returns correct job totals, zero handler totals."""
        db_svc, session_id = db

        j1 = await insert_job(db_svc, app_key="job_only", job_name="scheduled")
        await insert_execution(db_svc, j1, session_id, status="success", duration_ms=40.0)
        await insert_execution(db_svc, j1, session_id, status="timed_out", duration_ms=90.0)

        agg = await query_service.get_app_health_aggregates(app_key="job_only", instance_index=0)

        assert agg.total_invocations == 0
        assert agg.handler_errors == 0
        assert agg.handler_avg_duration_ms == 0.0
        assert agg.total_executions == 2
        assert agg.job_errors == 0
        assert agg.job_timed_out == 1
        assert agg.job_avg_duration_ms == pytest.approx(65.0)

    async def test_since_filters_handler_and_job_counts(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since parameter restricts both handler invocations and job executions by timestamp."""
        db_svc, session_id = db

        since_ts = BASE_TS + 50.0

        l1 = await insert_listener(db_svc, app_key="windowed_app", handler_method="on_event")
        # Before since: should not count
        await insert_invocation(
            db_svc, l1, session_id, status="error", duration_ms=5.0, execution_start_ts=BASE_TS + 10.0
        )
        # After since: should count
        await insert_invocation(
            db_svc, l1, session_id, status="success", duration_ms=20.0, execution_start_ts=BASE_TS + 100.0
        )

        j1 = await insert_job(db_svc, app_key="windowed_app", job_name="windowed_job")
        # Before since: should not count
        await insert_execution(
            db_svc, j1, session_id, status="timed_out", duration_ms=15.0, execution_start_ts=BASE_TS + 5.0
        )
        # After since: should count
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=60.0, execution_start_ts=BASE_TS + 200.0
        )

        agg = await query_service.get_app_health_aggregates(app_key="windowed_app", instance_index=0, since=since_ts)

        # Only post-since records counted
        assert agg.total_invocations == 1
        assert agg.handler_errors == 0
        assert agg.handler_avg_duration_ms == pytest.approx(20.0)

        assert agg.total_executions == 1
        assert agg.job_timed_out == 0
        assert agg.job_avg_duration_ms == pytest.approx(60.0)

    async def test_last_activity_ts_is_most_recent_across_both_tables(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """last_activity_ts is the max of handler and job timestamps."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, app_key="ts_app", handler_method="on_event")
        j1 = await insert_job(db_svc, app_key="ts_app", job_name="ts_job")

        await insert_invocation(
            db_svc, l1, session_id, status="success", duration_ms=5.0, execution_start_ts=BASE_TS + 10.0
        )
        await insert_execution(
            db_svc, j1, session_id, status="success", duration_ms=5.0, execution_start_ts=BASE_TS + 99.0
        )

        agg = await query_service.get_app_health_aggregates(app_key="ts_app", instance_index=0)

        # Max of the two timestamps
        assert agg.last_activity_ts == pytest.approx(BASE_TS + 99.0)

    async def test_instance_index_scoping(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Only records for the specified instance_index are counted."""
        db_svc, session_id = db

        l0 = await insert_listener(db_svc, app_key="multi_inst", instance_index=0, handler_method="on_event")
        l1 = await insert_listener(db_svc, app_key="multi_inst", instance_index=1, handler_method="on_event")

        await insert_invocation(db_svc, l0, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l0, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="error", duration_ms=50.0)

        # Query instance 0 only — should see 2 successes, no errors
        agg = await query_service.get_app_health_aggregates(app_key="multi_inst", instance_index=0)
        assert agg.total_invocations == 2
        assert agg.handler_errors == 0

        # Query instance 1 only — should see 1 error
        agg1 = await query_service.get_app_health_aggregates(app_key="multi_inst", instance_index=1)
        assert agg1.total_invocations == 1
        assert agg1.handler_errors == 1


class TestGetListenerSummaryGlobal:
    async def test_returns_all_listeners_across_apps_and_instances(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """All listeners from multiple apps and instances are returned in a single call."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, app_key="app_alpha", instance_index=0, handler_method="on_alpha")
        l2 = await insert_listener(db_svc, app_key="app_beta", instance_index=0, handler_method="on_beta")
        l3 = await insert_listener(db_svc, app_key="app_alpha", instance_index=1, handler_method="on_alpha_1")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=5.0)
        await insert_invocation(db_svc, l2, session_id, status="error", duration_ms=20.0)

        results = await query_service.get_listener_summary()

        assert len(results) == 3
        assert all(isinstance(r, ListenerSummary) for r in results)

        listener_ids = {r.listener_id for r in results}
        assert listener_ids == {l1, l2, l3}

        app_keys = {r.app_key for r in results}
        assert app_keys == {"app_alpha", "app_beta"}

    async def test_matches_per_instance_get_listener_summary_combined(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Results match the union of per-instance get_listener_summary() calls."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, app_key="app_x", instance_index=0, handler_method="on_x0")
        l2 = await insert_listener(db_svc, app_key="app_y", instance_index=0, handler_method="on_y0")

        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=10.0)
        await insert_invocation(db_svc, l1, session_id, status="success", duration_ms=20.0)
        await insert_invocation(db_svc, l2, session_id, status="error", duration_ms=5.0)

        global_results = await query_service.get_listener_summary(source_tier="all")

        per_x = await query_service.get_listener_summary(app_key="app_x", instance_index=0, source_tier="all")
        per_y = await query_service.get_listener_summary(app_key="app_y", instance_index=0, source_tier="all")
        combined = {r.listener_id: r for r in per_x + per_y}

        assert len(global_results) == len(combined)
        for r in global_results:
            expected = combined[r.listener_id]
            assert r.total_invocations == expected.total_invocations
            assert r.failed == expected.failed
            assert r.avg_duration_ms == pytest.approx(expected.avg_duration_ms)

    async def test_last_error_row_coherence(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Multiple errors — all last_error_* columns come from the same (most recent) error row."""
        db_svc, session_id = db

        l1 = await insert_listener(db_svc, app_key="coh_app", handler_method="on_event")

        await insert_invocation(
            db_svc,
            l1,
            session_id,
            status="error",
            error_type="OldError",
            error_message="old message",
            error_traceback="old traceback",
            execution_start_ts=BASE_TS + 1.0,
        )
        await insert_invocation(
            db_svc,
            l1,
            session_id,
            status="error",
            error_type="NewError",
            error_message="new message",
            error_traceback="new traceback",
            execution_start_ts=BASE_TS + 10.0,
        )

        results = await query_service.get_listener_summary()
        assert len(results) == 1
        row = results[0]

        # All columns must come from the same (most recent) row
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "new message"
        assert row.last_error_traceback == "new traceback"

    async def test_source_tier_app_excludes_framework(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='app' excludes framework-tier listeners."""
        db_svc, _ = db

        await insert_listener(db_svc, app_key="my_app", handler_method="on_event", source_tier="app")
        await insert_listener(
            db_svc, app_key="__hassette__Internal", handler_method="on_internal", source_tier="framework"
        )

        results = await query_service.get_listener_summary(source_tier="app")

        assert len(results) == 1
        assert results[0].source_tier == "app"

    async def test_source_tier_all_includes_both_tiers(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """source_tier='all' returns both app and framework tier listeners."""
        db_svc, _ = db

        await insert_listener(db_svc, app_key="my_app", handler_method="on_event", source_tier="app")
        await insert_listener(
            db_svc, app_key="__hassette__Internal", handler_method="on_internal", source_tier="framework"
        )

        results = await query_service.get_listener_summary(source_tier="all")

        assert len(results) == 2
        tiers = {r.source_tier for r in results}
        assert tiers == {"app", "framework"}

    async def test_since_filter_restricts_invocation_counts(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """since parameter filters invocations — listeners still appear but with lower counts."""
        db_svc, session_id = db

        since_ts = BASE_TS + 50.0
        l1 = await insert_listener(db_svc, app_key="windowed", handler_method="on_event")

        # Before since: should not count in aggregates
        await insert_invocation(
            db_svc, l1, session_id, status="error", duration_ms=5.0, execution_start_ts=BASE_TS + 10.0
        )
        # After since: should count
        await insert_invocation(
            db_svc, l1, session_id, status="success", duration_ms=20.0, execution_start_ts=BASE_TS + 100.0
        )

        results = await query_service.get_listener_summary(since=since_ts)

        assert len(results) == 1
        row = results[0]
        assert row.total_invocations == 1
        assert row.failed == 0

    async def test_no_listeners_returns_empty_list(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Empty database returns empty list."""
        results = await query_service.get_listener_summary()
        assert results == []

    async def test_since_filter_scopes_error_cte(
        self,
        query_service: TelemetryQueryService,
        db: tuple[DatabaseService, int],
    ) -> None:
        """Error before the since window is excluded from last_error_* fields."""
        db_svc, session_id = db
        since_ts = BASE_TS + 50.0

        l1 = await insert_listener(db_svc, app_key="my_app", handler_method="on_event")
        await insert_invocation(
            db_svc,
            l1,
            session_id,
            status="error",
            error_type="OldError",
            error_message="before window",
            execution_start_ts=BASE_TS + 1.0,
        )
        await insert_invocation(
            db_svc,
            l1,
            session_id,
            status="error",
            error_type="NewError",
            error_message="inside window",
            execution_start_ts=BASE_TS + 100.0,
        )

        results = await query_service.get_listener_summary(since=since_ts)
        assert len(results) == 1
        row = results[0]
        assert row.last_error_type == "NewError"
        assert row.last_error_message == "inside window"
