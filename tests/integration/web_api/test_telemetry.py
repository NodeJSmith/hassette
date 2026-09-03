"""Integration tests for telemetry web API endpoints."""

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.core.telemetry.query_service import AppHealthAggregates
from hassette.schemas.live_counts import LiveCounts
from hassette.test_utils.web_manifest_helpers import make_manifest_db_row
from hassette.test_utils.web_telemetry_helpers import make_execution, make_listener_summary

from .conftest import APP_GRID_PATH, APP_HEALTH_PATH, TELEMETRY_STATUS_PATH, get_json, telemetry_error

MOCK_TS = 1_234_567_890.0

if TYPE_CHECKING:
    from httpx2 import AsyncClient

APP_LISTENERS_PATH = "/api/telemetry/app/my_app/listeners"

# The listener shape every test in TestTelemetryListeners starts from; each overrides only the
# fields it asserts on.
LISTENER_DEFAULTS: dict[str, Any] = {
    "app_key": "my_app",
    "handler_method": "on_light",
    "topic": "state_changed.light.kitchen",
    "source_location": "my_app.py:10",
}


async def assert_forwarded_to_service(
    client: "AsyncClient", mock_hassette: MagicMock, *, path: str, service_method: str, expected: dict[str, Any]
) -> None:
    """GET `path` (expecting 200) and assert the query params reached the service call as `expected`.

    These routes are pure pass-throughs for `since`/`limit`/`source_tier`/`app_key`, so the
    behavior under test is entirely "what did the service get called with".
    """
    await get_json(client, path)

    call_kwargs = getattr(mock_hassette.telemetry_query_service, service_method).call_args.kwargs
    assert {key: call_kwargs[key] for key in expected} == expected


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
                last_activity_ts=MOCK_TS,
            )
        )

        data = await get_json(client, APP_HEALTH_PATH)

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
                last_activity_ts=MOCK_TS,
            )
        )

        data = await get_json(client, APP_HEALTH_PATH)

        # 20 failures / 100 total = 20% error → 80% success → "critical".
        assert data["error_rate"] == pytest.approx(20.0)
        assert data["health_status"] == "critical"

    async def test_unknown_app_returns_empty_health(self, client: "AsyncClient") -> None:
        data = await get_json(client, "/api/telemetry/app/nonexistent/health")

        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"

    async def test_instance_index_param(self, client: "AsyncClient", mock_hassette) -> None:
        await get_json(client, f"{APP_HEALTH_PATH}?instance_index=1")

        mock_hassette.telemetry_query_service.get_app_health_aggregates.assert_called_once()
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args
        assert call_kwargs.kwargs.get("instance_index") == 1 or call_kwargs[1].get("instance_index") == 1


class TestTelemetryListeners:
    async def test_returns_summaries_with_handler_descriptions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                make_listener_summary(
                    **LISTENER_DEFAULTS,
                    listener_id=1,
                    total_invocations=50,
                    successful=50,
                    total_duration_ms=2500.0,
                    avg_duration_ms=50.0,
                    min_duration_ms=10.0,
                    max_duration_ms=200.0,
                    last_invoked_at=MOCK_TS,
                )
            ]
        )

        data = await get_json(client, APP_LISTENERS_PATH)

        assert len(data) == 1
        assert data[0]["handler_summary"] == "light.kitchen"
        assert data[0]["listener_id"] == 1

    async def test_returns_mode_and_live_counts(self, client: "AsyncClient", mock_hassette) -> None:
        """The endpoint surfaces persisted mode and live suppressed/dropped counts."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            return_value=[
                make_listener_summary(
                    **LISTENER_DEFAULTS,
                    listener_id=7,
                    mode="single",
                    backpressure="drop_newest",
                    total_invocations=3,
                    successful=3,
                    total_duration_ms=30.0,
                    avg_duration_ms=10.0,
                    min_duration_ms=10.0,
                    max_duration_ms=10.0,
                    last_invoked_at=MOCK_TS,
                )
            ]
        )
        # Live snapshot keyed by listener db_id (== listener_id 7).
        mock_hassette.bus_service.live_execution_counts = MagicMock(
            return_value={7: LiveCounts(suppressed=2, dropped=4, backpressure_dropped=5)}
        )

        data = await get_json(client, APP_LISTENERS_PATH)

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
            return_value=[make_listener_summary(**LISTENER_DEFAULTS, listener_id=7, mode="restart")]
        )
        mock_hassette.bus_service.live_execution_counts = MagicMock(return_value={})

        data = await get_json(client, APP_LISTENERS_PATH)

        assert data[0]["mode"] == "restart"
        assert data[0]["suppressed_count"] == 0
        assert data[0]["dropped_count"] == 0


class TestTelemetryDashboard:
    async def test_app_grid_returns_per_app_health(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """The grid spine is DB-sourced; entries carry both telemetry and manifest metadata."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[make_manifest_db_row(app_key="my_app")]
        )

        data = await get_json(client, APP_GRID_PATH)

        assert isinstance(data["apps"], list)
        assert len(data["apps"]) == 1
        app_entry = data["apps"][0]
        assert app_entry["app_key"] == "my_app"
        assert "health_status" in app_entry
        assert "status" in app_entry
        # Manifest metadata fields are present alongside telemetry data.
        assert app_entry["class_name"] == "MyApp"
        assert app_entry["filename"] == "my_app.py"
        assert app_entry["in_current_config"] is False

    async def test_app_grid_includes_db_only_apps(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """A DB-only app (no matching in-memory manifest) appears in the grid."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[
                make_manifest_db_row(
                    app_key="orphan_app",
                    class_name="OrphanApp",
                    display_name="Orphan App",
                    filename="orphan_app.py",
                )
            ]
        )

        data = await get_json(client, APP_GRID_PATH)

        orphan = next(e for e in data["apps"] if e["app_key"] == "orphan_app")
        assert orphan["status"] == "stopped"
        assert orphan["in_current_config"] is False
        assert orphan["instance_count"] == 0

    async def test_app_grid_returns_503_on_spine_failure(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """A storage error on the DB spine query yields 503."""
        mock_hassette.telemetry_query_service.get_all_app_manifests = telemetry_error("db down")

        assert await get_json(client, APP_GRID_PATH, expect_status=503) == {"apps": []}


class TestTelemetryExecutions:
    async def test_list_executions_returns_all(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[
                make_execution(kind="handler", listener_id=1, execution_start_ts=MOCK_TS, duration_ms=42.5),
                make_execution(kind="job", job_id=7, execution_start_ts=1234567891.0, duration_ms=100.0),
            ]
        )

        data = await get_json(client, "/api/telemetry/executions")

        assert len(data) == 2
        assert data[0]["kind"] == "handler"
        assert data[1]["kind"] == "job"

    async def test_list_executions_kind_filter_forwarded(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])

        await assert_forwarded_to_service(
            client,
            mock_hassette,
            path="/api/telemetry/executions?kind=handler",
            service_method="get_executions",
            expected={"kind": "handler"},
        )

    async def test_listener_executions_returns_handler_executions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[make_execution(kind="handler", listener_id=1, execution_start_ts=MOCK_TS, duration_ms=42.5)]
        )

        data = await get_json(client, "/api/telemetry/listener/1/executions")

        assert len(data) == 1
        assert data[0]["duration_ms"] == 42.5
        assert data[0]["kind"] == "handler"
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["listener_id"] == 1

    async def test_job_executions_returns_job_executions(self, client: "AsyncClient", mock_hassette) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[make_execution(kind="job", job_id=1, execution_start_ts=MOCK_TS, duration_ms=100.0)]
        )

        data = await get_json(client, "/api/telemetry/job/1/executions")

        assert len(data) == 1
        assert data[0]["status"] == "success"
        assert data[0]["kind"] == "job"
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["job_id"] == 1


class TestTelemetryStatus:
    async def test_telemetry_status_healthy(self, client: "AsyncClient") -> None:
        """/api/telemetry/status returns 200 with degraded=false when DB is healthy."""
        data = await get_json(client, TELEMETRY_STATUS_PATH)

        assert data["degraded"] is False

    async def test_telemetry_status_db_unavailable(self, client: "AsyncClient", mock_hassette) -> None:
        """/api/telemetry/status returns 503 with degraded=true when the query raises TelemetryUnavailableError."""
        mock_hassette.telemetry_query_service.check_health = telemetry_error()

        data = await get_json(client, TELEMETRY_STATUS_PATH, expect_status=503)

        assert data["degraded"] is True


class TestQueryParamForwarding:
    """Every telemetry route forwards its query params verbatim to the query service.

    `since`, `limit`, and `source_tier` are pure pass-throughs — a route that drops one silently
    returns unfiltered data, which is why each (route, param) pair is pinned individually rather
    than spot-checked on one representative route.
    """

    @pytest.mark.parametrize(
        ("path", "service_method", "expected"),
        [
            # since= is forwarded on every route that accepts it...
            (
                "/api/telemetry/app/my_app/health?since=1700000000.0",
                "get_app_health_aggregates",
                {"since": pytest.approx(1700000000.0)},
            ),
            (
                "/api/telemetry/app/my_app/listeners?since=1700000007.0",
                "get_listener_summary",
                {"since": pytest.approx(1700000007.0)},
            ),
            (
                "/api/telemetry/app/my_app/jobs?since=1700000003.0",
                "get_job_summary",
                {"since": pytest.approx(1700000003.0)},
            ),
            (
                "/api/telemetry/listener/1/executions?since=1700000005.0",
                "get_executions",
                {"since": pytest.approx(1700000005.0)},
            ),
            (
                "/api/telemetry/job/1/executions?since=1700000009.0",
                "get_executions",
                {"since": pytest.approx(1700000009.0)},
            ),
            (
                "/api/telemetry/app/my_app/activity?since=1700000011.0",
                "get_app_recent_activity",
                {"since": pytest.approx(1700000011.0)},
            ),
            (
                "/api/telemetry/dashboard/app-grid?since=1700000013.0",
                "get_all_app_summaries",
                {"since": pytest.approx(1700000013.0)},
            ),
            # ...and omitting it passes None rather than a default window.
            ("/api/telemetry/app/my_app/health", "get_app_health_aggregates", {"since": None}),
            ("/api/telemetry/listener/1/executions", "get_executions", {"since": None}),
            ("/api/telemetry/app/my_app/activity", "get_app_recent_activity", {"since": None}),
            # limit= and source_tier= travel the same path.
            ("/api/telemetry/app/my_app/activity?limit=10", "get_app_recent_activity", {"limit": 10}),
            ("/api/telemetry/app/my_app/health?source_tier=all", "get_app_health_aggregates", {"source_tier": "all"}),
            (
                "/api/telemetry/app/my_app/listeners?source_tier=framework",
                "get_listener_summary",
                {"source_tier": "framework"},
            ),
            ("/api/telemetry/app/my_app/jobs?source_tier=all", "get_job_summary", {"source_tier": "all"}),
            ("/api/telemetry/app/my_app/activity?source_tier=all", "get_app_recent_activity", {"source_tier": "all"}),
        ],
    )
    async def test_query_param_reaches_service(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
        path: str,
        service_method: str,
        expected: dict[str, Any],
    ) -> None:
        await assert_forwarded_to_service(
            client, mock_hassette, path=path, service_method=service_method, expected=expected
        )

    async def test_app_health_invalid_source_tier_returns_422(self, client: "AsyncClient") -> None:
        """Invalid source_tier on /health returns 422."""
        response = await client.get(f"{APP_HEALTH_PATH}?source_tier=bad")
        assert response.status_code == 422


class TestBusListenersSinceParam:
    """Verify query params propagate through /bus/listeners, whose app_key handling is special."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/api/bus/listeners?app_key=my_app&since=1700000020.0", {"since": pytest.approx(1700000020.0)}),
            ("/api/bus/listeners?app_key=my_app", {"since": None}),
            # No app_key at all routes to the all-apps query.
            ("/api/bus/listeners?since=1700000020.0", {"app_key": None, "since": pytest.approx(1700000020.0)}),
        ],
    )
    async def test_bus_listeners_forwards_params(
        self, client: "AsyncClient", mock_hassette: MagicMock, path: str, expected: dict[str, Any]
    ) -> None:
        await assert_forwarded_to_service(
            client, mock_hassette, path=path, service_method="get_listener_summary", expected=expected
        )

    async def test_bus_listeners_empty_string_app_key_does_not_route_to_all_apps(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """?app_key= (empty string) must not fall through to the all-apps path."""
        # Wire a non-empty return so we can tell if the all-apps path was taken
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(return_value=[])

        await get_json(client, "/api/bus/listeners?app_key=")

        # An empty app_key is not None — the unified method is called with app_key=""
        # (which finds nothing in the DB), NOT with app_key=None (full-table scan).
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["app_key"] == ""
        # Confirm app_key is not None — it did NOT go through the all-apps branch
        assert call_kwargs["app_key"] is not None


class TestExecutionListEndpoints:
    """Extended coverage for the per-listener and per-job execution list routes.

    Both routes share one service method (`get_executions`) and differ only in which id kwarg
    they forward, so each behavior is pinned against both to catch a route wiring the wrong one.
    """

    @pytest.mark.parametrize(
        ("path_prefix", "id_kwarg", "kind"),
        [("/api/telemetry/listener/1", "listener_id", "handler"), ("/api/telemetry/job/1", "job_id", "job")],
    )
    async def test_limit_param_respected(
        self, client: "AsyncClient", mock_hassette: MagicMock, path_prefix: str, id_kwarg: str, kind: str
    ) -> None:
        """When limit=2, the service is called with limit=2 and at most 2 results come back."""
        executions = [
            make_execution(kind=kind, **{id_kwarg: 1}, execution_start_ts=float(1000 + i), duration_ms=float(10 + i))
            for i in range(5)
        ]
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=executions[:2])

        data = await get_json(client, f"{path_prefix}/executions?limit=2")

        assert len(data) == 2
        call_kwargs = mock_hassette.telemetry_query_service.get_executions.call_args.kwargs
        assert call_kwargs["limit"] == 2
        assert call_kwargs[id_kwarg] == 1

    @pytest.mark.parametrize("path", ["/api/telemetry/listener/99/executions", "/api/telemetry/job/99/executions"])
    async def test_empty_result(self, client: "AsyncClient", mock_hassette: MagicMock, path: str) -> None:
        """An id with no executions returns an empty list."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])

        assert await get_json(client, path) == []

    @pytest.mark.parametrize(
        ("path_prefix", "id_kwarg", "kind"),
        [("/api/telemetry/listener/1", "listener_id", "handler"), ("/api/telemetry/job/1", "job_id", "job")],
    )
    async def test_ordering_descending_by_execution_start_ts(
        self, client: "AsyncClient", mock_hassette: MagicMock, path_prefix: str, id_kwarg: str, kind: str
    ) -> None:
        """Results are returned in descending execution_start_ts order (newest first)."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            return_value=[
                make_execution(kind=kind, **{id_kwarg: 1}, execution_start_ts=ts, duration_ms=10.0)
                for ts in [1000003.0, 1000002.0, 1000001.0]
            ]
        )

        data = await get_json(client, f"{path_prefix}/executions")

        assert len(data) == 3
        timestamps = [entry["execution_start_ts"] for entry in data]
        assert timestamps == sorted(timestamps, reverse=True)


class TestGetExecutionById:
    """Coverage for GET /api/telemetry/execution/{execution_id}."""

    async def test_found(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Returns the execution record when found."""
        mock_hassette.telemetry_query_service.get_execution_by_id = AsyncMock(
            return_value=make_execution(
                kind="handler",
                listener_id=5,
                execution_start_ts=1700000000.0,
                duration_ms=42.5,
                execution_id="abc-123",
            )
        )

        data = await get_json(client, "/api/telemetry/execution/abc-123")

        assert data["execution_id"] == "abc-123"
        assert data["kind"] == "handler"
        assert data["listener_id"] == 5
        assert data["duration_ms"] == 42.5
        mock_hassette.telemetry_query_service.get_execution_by_id.assert_awaited_once_with("abc-123")

    async def test_not_found(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Returns null when execution does not exist."""
        mock_hassette.telemetry_query_service.get_execution_by_id = AsyncMock(return_value=None)

        assert await get_json(client, "/api/telemetry/execution/nonexistent-id") is None

    async def test_db_unavailable(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Returns 503 when telemetry DB is unavailable."""
        mock_hassette.telemetry_query_service.get_execution_by_id = telemetry_error("db down")

        await get_json(client, "/api/telemetry/execution/abc-123", expect_status=503)
