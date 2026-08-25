"""Integration tests for validation, error guards, and edge cases in the web API."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from .conftest import APP_GRID_PATH, APP_HEALTH_PATH, TELEMETRY_STATUS_PATH, get_json, telemetry_error

if TYPE_CHECKING:
    from httpx2 import AsyncClient

# Each entry is a storage failure a route must degrade rather than 500 on. The message differs
# only to document which underlying error the service wrapped before raising.
WRAPPED_STORAGE_ERRORS = [
    pytest.param("database is locked", id="sqlite-error"),
    pytest.param("disk I/O error", id="oserror"),
    pytest.param("Connection is closed", id="closed-connection"),
]


class TestDbErrorGuards:
    """Verify TelemetryUnavailableError degradation guards on telemetry endpoints."""

    @pytest.mark.parametrize(
        ("service_method", "path"),
        [
            ("get_listener_summary", "/api/telemetry/app/my_app/listeners"),
            ("get_job_summary", "/api/telemetry/app/my_app/jobs"),
            ("get_app_recent_activity", "/api/telemetry/app/my_app/activity"),
            ("get_executions", "/api/telemetry/listener/1/executions"),
            ("get_executions", "/api/telemetry/job/1/executions"),
        ],
    )
    async def test_collection_endpoint_db_error_returns_503_with_empty_list(
        self, client: "AsyncClient", mock_hassette: MagicMock, service_method: str, path: str
    ) -> None:
        """TelemetryUnavailableError on a list-returning endpoint yields 503 with an empty list."""
        setattr(mock_hassette.telemetry_query_service, service_method, telemetry_error())

        assert await get_json(client, path, expect_status=503) == []

    async def test_app_health_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on app_health returns 503 with zero-value response."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = telemetry_error()

        data = await get_json(client, APP_HEALTH_PATH, expect_status=503)

        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"


class TestStatusDropCounters:
    """Verify /telemetry/status returns dropped_overflow and dropped_exhausted."""

    @pytest.mark.parametrize(
        ("counters", "expected"),
        [
            ((0, 0, 0), (0, 0, 0)),
            ((7, 3, 1), (7, 3, 1)),
        ],
        ids=["all-zero", "non-zero"],
    )
    async def test_drop_counters_surface_in_status(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
        counters: tuple[int, int, int],
        expected: tuple[int, int, int],
    ) -> None:
        """Counters from Hassette.get_drop_counters() appear verbatim in the response."""
        mock_hassette.get_drop_counters.return_value = counters

        data = await get_json(client, TELEMETRY_STATUS_PATH)

        assert (data["dropped_overflow"], data["dropped_exhausted"], data["dropped_shutdown"]) == expected

    async def test_status_degraded_has_zero_drop_counters(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When DB is degraded, dropped counters default to 0 (safe fallback)."""
        mock_hassette.telemetry_query_service.check_health = telemetry_error()

        data = await get_json(client, TELEMETRY_STATUS_PATH, expect_status=503)

        assert data["degraded"] is True
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


class TestHassetteAppKey:
    """Verify __hassette__ app_key returns framework data (OpenAPI doc coverage)."""

    @pytest.mark.parametrize(
        ("path", "service_method"),
        [
            ("/api/telemetry/app/__hassette__/health", "get_app_health_aggregates"),
            ("/api/telemetry/app/__hassette__/listeners", "get_listener_summary"),
        ],
    )
    async def test_hassette_app_key_accepted(
        self, client: "AsyncClient", mock_hassette: MagicMock, path: str, service_method: str
    ) -> None:
        """The reserved framework app_key is accepted (200) and forwarded to the service."""
        await get_json(client, path)

        call_kwargs = getattr(mock_hassette.telemetry_query_service, service_method).call_args.kwargs
        assert call_kwargs["app_key"] == "__hassette__"


class TestTelemetryStatusDropCounterFallback:
    """AttributeError/RuntimeError fallback for get_drop_counters."""

    @pytest.mark.parametrize(
        "error",
        [AttributeError("no such attribute"), RuntimeError("not yet initialised")],
        ids=["attribute-error", "runtime-error"],
    )
    async def test_get_drop_counters_failure_returns_zeros(
        self, client: "AsyncClient", mock_hassette: MagicMock, error: Exception
    ) -> None:
        """A get_drop_counters failure falls back to zero counters without degrading the route."""
        mock_hassette.get_drop_counters.side_effect = error

        data = await get_json(client, TELEMETRY_STATUS_PATH)

        assert data["degraded"] is False
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0
        assert data["dropped_shutdown"] == 0


class TestAppHealthDbErrorFallback:
    """TelemetryUnavailableError degradation guard on the app_health endpoint.

    The message varies across cases to document which underlying storage error the service
    wrapped (sqlite3.Error, OSError, a closed-connection ValueError); the guard must degrade
    identically for all of them.
    """

    @pytest.mark.parametrize("message", WRAPPED_STORAGE_ERRORS)
    async def test_telemetry_unavailable_returns_503_with_zeroed_health(
        self, client: "AsyncClient", mock_hassette: MagicMock, message: str
    ) -> None:
        """TelemetryUnavailableError on get_app_health_aggregates returns 503 with zero-value health."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = telemetry_error(message)

        data = await get_json(client, APP_HEALTH_PATH, expect_status=503)

        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"
        assert data["handler_avg_duration"] == 0.0
        assert data["job_avg_duration"] == 0.0
        assert data["last_activity_ts"] is None


class TestDashboardAppGridDbErrorFallback:
    """TelemetryUnavailableError degradation guard on dashboard_app_grid (category-C, silent-200).

    The enrichment query failing must leave the response at 200 with zeroed per-app entries --
    the DB spine query succeeds independently, so every manifest entry still appears.
    """

    @pytest.mark.parametrize("message", WRAPPED_STORAGE_ERRORS)
    async def test_telemetry_unavailable_returns_200_with_zeroed_entries(
        self, client: "AsyncClient", mock_hassette: MagicMock, message: str
    ) -> None:
        """get_all_app_summaries raising falls back to an empty summaries dict, not a 500."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = telemetry_error(message)

        data = await get_json(client, APP_GRID_PATH)

        assert "apps" in data
        for entry in data["apps"]:
            assert entry["total_invocations"] == 0
            assert entry["total_errors"] == 0
            assert entry["handler_count"] == 0
            assert entry["job_count"] == 0
            # total_invocations=0 and total_executions=0 -> error_rate=0.0, and a zero-invocation
            # app is classified "excellent" (not "unknown").
            assert entry["error_rate"] == 0.0
            assert entry["health_status"] == "excellent"


class TestAppKeyValidation:
    """Verify that invalid app_key values are rejected with 400 on management routes.

    The validation is performed by _validate_app_key() in apps.py using the regex
    ``^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$``. It raises HTTPException(400), not 422.
    """

    @pytest.mark.parametrize(
        ("action", "app_key"),
        [
            (action, key)
            for action in ("start", "stop", "reload")
            for key in (
                "!!invalid",
                "0starts_with_digit",
                "-starts_with_dash",
                "a" * 129,  # exceeds 128-char limit (pattern allows 1 + up to 127 = 128 total)
            )
        ],
    )
    async def test_invalid_app_key_returns_400(self, client: "AsyncClient", action: str, app_key: str) -> None:
        """Invalid app_key format returns 400 on all management actions."""
        response = await client.post(f"/api/apps/{app_key}/{action}")
        assert response.status_code == 400

    @pytest.mark.parametrize("action", ["start", "stop", "reload"])
    async def test_nonexistent_app_key_returns_404(
        self, client: "AsyncClient", mock_hassette: MagicMock, action: str
    ) -> None:
        """Non-existent app_key returns 404 when registry has no manifest and no running instances."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        mock_hassette._app_handler.registry.get_instances.return_value = {}
        response = await client.post(f"/api/apps/unknown_app/{action}")
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "app_key",
        ["my_app.v2", "a" + "b" * 127],
        ids=["dots-and-underscores", "exactly-128-chars"],
    )
    async def test_valid_app_key_accepted(self, client: "AsyncClient", app_key: str) -> None:
        """app_key forms the regex permits are accepted (1 letter + up to 127 more)."""
        response = await client.post(f"/api/apps/{app_key}/start")
        assert response.status_code == 202


class TestLimitParameterValidation:
    """Verify out-of-range limit parameters return 422 across all relevant endpoints."""

    @pytest.mark.parametrize(
        ("path", "limit"),
        [
            ("/api/logs/recent", 0),
            ("/api/logs/recent", 2001),
            ("/api/telemetry/listener/1/executions", 0),
            ("/api/telemetry/listener/1/executions", 501),
            ("/api/telemetry/job/1/executions", 0),
            ("/api/telemetry/job/1/executions", 501),
        ],
    )
    async def test_out_of_range_limit_returns_422(self, client: "AsyncClient", path: str, limit: int) -> None:
        response = await client.get(f"{path}?limit={limit}")
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("path", "limit"),
        [
            ("/api/logs/recent", 2000),
            ("/api/telemetry/listener/1/executions", 500),
            ("/api/telemetry/job/1/executions", 500),
        ],
    )
    async def test_limit_at_max_accepted(
        self, client: "AsyncClient", mock_hassette: MagicMock, path: str, limit: int
    ) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get(f"{path}?limit={limit}")
        assert response.status_code == 200
