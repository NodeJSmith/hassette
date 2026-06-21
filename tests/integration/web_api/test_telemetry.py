"""Integration tests for telemetry web API endpoints."""

import sqlite3
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.telemetry.query_service import AppHealthAggregates
from hassette.schemas.live_counts import LiveCounts
from hassette.schemas.telemetry_models import (
    Execution,
    ListenerSummary,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestTelemetryAppHealth:
    async def test_returns_metrics_with_classification(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            return_value=AppHealthAggregates(
                total_invocations=100,
                handler_errors=5,
                handler_timed_out=0,
                handler_avg_duration_ms=50.0,
                total_executions=0,
                job_errors=0,
                job_timed_out=0,
                job_avg_duration_ms=0.0,
                last_activity_ts=1234567890.0,
            )
        )

        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        data = response.json()
        assert "error_rate" in data
        assert "error_rate_class" in data
        assert "health_status" in data
        assert data["error_rate"] == pytest.approx(5.0)
        assert data["error_rate_class"] == "warn"
        # success_rate = 100 - 5 = 95 → "good" (>= 95 threshold). Pins the
        # success-rate derivation from the clamped error rate.
        assert data["health_status"] == "good"

    async def test_health_status_critical_for_high_error_rate(self, client: "AsyncClient", mock_hassette) -> None:
        """20 failures of 100 → 80% success → 'critical'; success derives from the clamped error rate."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            return_value=AppHealthAggregates(
                total_invocations=80,
                handler_errors=10,
                handler_timed_out=5,
                handler_avg_duration_ms=50.0,
                total_executions=20,
                job_errors=3,
                job_timed_out=2,
                job_avg_duration_ms=10.0,
                last_activity_ts=1234567890.0,
            )
        )

        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        data = response.json()
        # 20 failures / 100 total = 20% error → 80% success → "critical".
        assert data["error_rate"] == pytest.approx(20.0)
        assert data["health_status"] == "critical"

    async def test_unknown_app_returns_empty_health(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/app/nonexistent/health")
        assert response.status_code == 200
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"

    async def test_instance_index_param(self, client: "AsyncClient", mock_hassette) -> None:
        response = await client.get("/api/telemetry/app/my_app/health?instance_index=1")
        assert response.status_code == 200
        mock_hassette.telemetry_query_service.get_app_health_aggregates.assert_called_once()
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args
        assert call_kwargs.kwargs.get("instance_index") == 1 or call_kwargs[1].get("instance_index") == 1


class TestTelemetryListeners:
    async def test_returns_summaries_with_handler_descriptions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                ListenerSummary(
                    listener_id=1,
                    app_key="my_app",
                    instance_index=0,
                    handler_method="on_light",
                    topic="state_changed.light.kitchen",
                    debounce=None,
                    throttle=None,
                    once=0,
                    priority=0,
                    predicate_description=None,
                    human_description=None,
                    source_location="my_app.py:10",
                    registration_source=None,
                    total_invocations=50,
                    successful=50,
                    failed=0,
                    di_failures=0,
                    cancelled=0,
                    total_duration_ms=2500.0,
                    avg_duration_ms=50.0,
                    min_duration_ms=10.0,
                    max_duration_ms=200.0,
                    last_invoked_at=1234567890.0,
                    last_error_type=None,
                    last_error_message=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["handler_summary"] == "light.kitchen"
        assert data[0]["listener_id"] == 1

    async def test_returns_mode_and_live_counts(self, client: "AsyncClient", mock_hassette) -> None:
        """The endpoint surfaces persisted mode and live suppressed/dropped counts."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                ListenerSummary(
                    listener_id=7,
                    app_key="my_app",
                    instance_index=0,
                    handler_method="on_light",
                    topic="state_changed.light.kitchen",
                    debounce=None,
                    throttle=None,
                    once=0,
                    priority=0,
                    predicate_description=None,
                    human_description=None,
                    source_location="my_app.py:10",
                    registration_source=None,
                    mode="single",
                    backpressure="drop_newest",
                    total_invocations=3,
                    successful=3,
                    failed=0,
                    di_failures=0,
                    cancelled=0,
                    total_duration_ms=30.0,
                    avg_duration_ms=10.0,
                    min_duration_ms=10.0,
                    max_duration_ms=10.0,
                    last_invoked_at=1234567890.0,
                    last_error_type=None,
                    last_error_message=None,
                )
            ]
        )
        # Live snapshot keyed by listener db_id (== listener_id 7).
        mock_hassette.bus_service.live_execution_counts = MagicMock(
            return_value={7: LiveCounts(suppressed=2, dropped=4, backpressure_dropped=5)}
        )

        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["mode"] == "single"
        assert data[0]["suppressed_count"] == 2
        assert data[0]["dropped_count"] == 4
        # The live backpressure_dropped count and the persisted policy both reach the HTTP response.
        assert data[0]["backpressure_dropped_count"] == 5
        assert data[0]["backpressure"] == "drop_newest"

    async def test_listener_with_no_live_guard_reports_zero_counts(self, client: "AsyncClient", mock_hassette) -> None:
        """A listener absent from the live snapshot (retired) reports zero counts."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                ListenerSummary(
                    listener_id=7,
                    app_key="my_app",
                    instance_index=0,
                    handler_method="on_light",
                    topic="state_changed.light.kitchen",
                    debounce=None,
                    throttle=None,
                    once=0,
                    priority=0,
                    predicate_description=None,
                    human_description=None,
                    source_location="my_app.py:10",
                    registration_source=None,
                    mode="restart",
                    total_invocations=0,
                    successful=0,
                    failed=0,
                    di_failures=0,
                    cancelled=0,
                    total_duration_ms=0.0,
                    avg_duration_ms=0.0,
                    min_duration_ms=None,
                    max_duration_ms=None,
                    last_invoked_at=None,
                    last_error_type=None,
                    last_error_message=None,
                )
            ]
        )
        mock_hassette.bus_service.live_execution_counts = MagicMock(return_value={})

        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 200
        data = response.json()
        assert data[0]["mode"] == "restart"
        assert data[0]["suppressed_count"] == 0
        assert data[0]["dropped_count"] == 0


class TestTelemetryDashboard:
    async def test_app_grid_returns_per_app_health(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        assert isinstance(data["apps"], list)
        # Default mock has apps from the manifest snapshot
        for app_entry in data["apps"]:
            assert "app_key" in app_entry
            assert "health_status" in app_entry
            assert "status" in app_entry


class TestTelemetryExecutions:
    async def test_list_executions_returns_all(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[
                Execution(
                    kind="handler",
                    listener_id=1,
                    execution_start_ts=1234567890.0,
                    duration_ms=42.5,
                    status="success",
                    error_type=None,
                    error_message=None,
                ),
                Execution(
                    kind="job",
                    job_id=7,
                    execution_start_ts=1234567891.0,
                    duration_ms=100.0,
                    status="success",
                    error_type=None,
                    error_message=None,
                ),
            ]
        )
        response = await client.get("/api/telemetry/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["kind"] == "handler"
        assert data[1]["kind"] == "job"

    async def test_list_executions_kind_filter_forwarded(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/executions?kind=handler")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["kind"] == "handler"

    async def test_listener_executions_returns_handler_executions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[
                Execution(
                    kind="handler",
                    listener_id=1,
                    execution_start_ts=1234567890.0,
                    duration_ms=42.5,
                    status="success",
                    error_type=None,
                    error_message=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/listener/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["duration_ms"] == 42.5
        assert data[0]["kind"] == "handler"
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["listener_id"] == 1

    async def test_job_executions_returns_job_executions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[
                Execution(
                    kind="job",
                    job_id=1,
                    execution_start_ts=1234567890.0,
                    duration_ms=100.0,
                    status="success",
                    error_type=None,
                    error_message=None,
                )
            ]
        )
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "success"
        assert data[0]["kind"] == "job"
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["job_id"] == 1


class TestTelemetryStatus:
    async def test_telemetry_status_healthy(self, client: "AsyncClient") -> None:
        """/api/telemetry/status returns 200 with degraded=false when DB is healthy."""
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False

    async def test_telemetry_status_db_unavailable(self, client: "AsyncClient", mock_hassette) -> None:
        """/api/telemetry/status returns 503 with degraded=true when DB query raises sqlite3.Error."""
        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=sqlite3.OperationalError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True


class TestTelemetrySinceParam:
    """Verify since query parameter propagates to telemetry service methods."""

    async def test_app_health_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health?since=1700000000.0 forwards since to service."""
        response = await client.get("/api/telemetry/app/my_app/health?since=1700000000.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000000.0)

    async def test_app_health_omitted_since_is_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health without since passes None."""
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args.kwargs
        assert call_kwargs["since"] is None

    async def test_app_listeners_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/listeners?since=1700000007.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000007.0)

    async def test_app_jobs_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/jobs?since=1700000003.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000003.0)

    async def test_listener_executions_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/listener/1/executions?since=1700000005.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000005.0)

    async def test_listener_executions_omitted_since_is_none(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/telemetry/listener/1/executions")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["since"] is None

    async def test_job_executions_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/job/1/executions?since=1700000009.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000009.0)

    async def test_app_activity_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/activity?since=1700000011.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000011.0)

    async def test_app_activity_passes_limit(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/app/my_app/activity?limit=10")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["limit"] == 10

    async def test_dashboard_app_grid_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/telemetry/dashboard/app-grid?since=1700000013.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_all_app_summaries.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000013.0)


class TestBusListenersSinceParam:
    """Verify since query parameter propagates through /bus/listeners."""

    async def test_bus_listeners_passes_since(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app&since=1700000020.0")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000020.0)

    async def test_bus_listeners_omitted_since_is_none(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        response = await client.get("/api/bus/listeners?app_key=my_app")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["since"] is None

    async def test_bus_listeners_without_app_key_calls_global_query(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        response = await client.get("/api/bus/listeners?since=1700000020.0")
        assert response.status_code == 200
        mock_hassette.telemetry_query_service.get_all_listeners_summary.assert_called_once()
        call_kwargs = mock_hassette.telemetry_query_service.get_all_listeners_summary.call_args.kwargs
        assert call_kwargs["since"] == pytest.approx(1700000020.0)
        mock_hassette.telemetry_query_service.get_listener_summary.assert_not_called()


class TestSourceTierParameter:
    """Verify source_tier query parameter is accepted and forwarded correctly."""

    async def test_app_health_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/health?source_tier=all passes source_tier to service."""
        response = await client.get("/api/telemetry/app/my_app/health?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_listeners_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/listeners?source_tier=framework passes through."""
        response = await client.get("/api/telemetry/app/my_app/listeners?source_tier=framework")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["source_tier"] == "framework"

    async def test_app_jobs_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/jobs?source_tier=all passes through."""
        response = await client.get("/api/telemetry/app/my_app/jobs?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_job_summary.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_activity_accepts_source_tier(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/{key}/activity?source_tier=all passes through."""
        response = await client.get("/api/telemetry/app/my_app/activity?source_tier=all")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_recent_activity.call_args.kwargs
        assert call_kwargs["source_tier"] == "all"

    async def test_app_health_invalid_source_tier_returns_422(self, client: "AsyncClient") -> None:
        """Invalid source_tier on /health returns 422."""
        response = await client.get("/api/telemetry/app/my_app/health?source_tier=bad")
        assert response.status_code == 422


class TestListenerExecutionsExpanded:
    """Extended coverage for /api/telemetry/listener/{id}/executions."""

    async def test_limit_param_respected(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """When limit=2, service is called with limit=2 and at most 2 results come back."""
        executions = [
            Execution(
                kind="handler",
                listener_id=1,
                execution_start_ts=float(1000 + i),
                duration_ms=float(10 + i),
                status="success",
                error_type=None,
                error_message=None,
            )
            for i in range(5)
        ]
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=executions[:2])
        response = await client.get("/api/telemetry/listener/1/executions?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["limit"] == 2
        assert call_kwargs["listener_id"] == 1

    async def test_empty_result(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Listener with no executions returns an empty list."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/listener/99/executions")
        assert response.status_code == 200
        assert response.json() == []

    async def test_ordering_descending_by_execution_start_ts(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Results are returned in descending execution_start_ts order (newest first)."""
        executions = [
            Execution(
                kind="handler",
                listener_id=1,
                execution_start_ts=ts,
                duration_ms=10.0,
                status="success",
                error_type=None,
                error_message=None,
            )
            for ts in [1000003.0, 1000002.0, 1000001.0]
        ]
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=executions)
        response = await client.get("/api/telemetry/listener/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        timestamps = [entry["execution_start_ts"] for entry in data]
        assert timestamps == sorted(timestamps, reverse=True)


class TestJobExecutionsExpanded:
    """Extended coverage for /api/telemetry/job/{id}/executions."""

    async def test_limit_param_respected(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """When limit=2, service is called with limit=2 and at most 2 results come back."""
        executions = [
            Execution(
                kind="job",
                job_id=1,
                execution_start_ts=float(2000 + i),
                duration_ms=float(50 + i),
                status="success",
                error_type=None,
                error_message=None,
            )
            for i in range(5)
        ]
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=executions[:2])
        response = await client.get("/api/telemetry/job/1/executions?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["limit"] == 2
        assert call_kwargs["job_id"] == 1

    async def test_empty_result(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Job with no executions returns an empty list."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/job/99/executions")
        assert response.status_code == 200
        assert response.json() == []

    async def test_ordering_descending_by_execution_start_ts(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """Results are returned in descending execution_start_ts order (newest first)."""
        executions = [
            Execution(
                kind="job",
                job_id=1,
                execution_start_ts=ts,
                duration_ms=100.0,
                status="success",
                error_type=None,
                error_message=None,
            )
            for ts in [2000003.0, 2000002.0, 2000001.0]
        ]
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=executions)
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        timestamps = [entry["execution_start_ts"] for entry in data]
        assert timestamps == sorted(timestamps, reverse=True)
