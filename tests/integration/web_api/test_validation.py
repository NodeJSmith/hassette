"""Integration tests for validation, error guards, and edge cases in the web API."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.exceptions import TelemetryUnavailableError

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestDbErrorGuards:
    """Verify TelemetryUnavailableError degradation guards on telemetry endpoints."""

    async def test_app_health_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on app_health returns 503 with zero-value response."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"

    async def test_app_listeners_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on app_listeners returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_listener_summary = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/listeners")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_app_jobs_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on app_jobs returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_job_summary = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/jobs")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_app_activity_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on app_activity returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_app_recent_activity = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/activity")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_listener_executions_db_error_returns_503(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError on listener executions returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/listener/1/executions")
        assert response.status_code == 503
        data = response.json()
        assert data == []

    async def test_job_executions_db_error_returns_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError on job executions returns 503 with empty list."""
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/job/1/executions")
        assert response.status_code == 503
        data = response.json()
        assert data == []


class TestStatusDropCounters:
    """Verify /telemetry/status returns dropped_overflow and dropped_exhausted."""

    async def test_status_includes_drop_counters_zero(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Healthy status includes drop counters defaulting to zero."""
        mock_hassette.get_drop_counters.return_value = (0, 0, 0)
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0
        assert data["dropped_shutdown"] == 0

    async def test_status_includes_nonzero_drop_counters(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """Non-zero drop counters from Hassette.get_drop_counters() appear in the response."""
        mock_hassette.get_drop_counters.return_value = (7, 3, 1)
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["dropped_overflow"] == 7
        assert data["dropped_exhausted"] == 3
        assert data["dropped_shutdown"] == 1

    async def test_status_degraded_has_zero_drop_counters(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When DB is degraded, dropped counters default to 0 (safe fallback)."""
        mock_hassette.telemetry_query_service.check_health = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


class TestHassetteAppKey:
    """Verify __hassette__ app_key returns framework data (OpenAPI doc coverage)."""

    async def test_hassette_app_key_accepted_on_health(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """GET /telemetry/app/__hassette__/health is accepted (200)."""
        response = await client.get("/api/telemetry/app/__hassette__/health")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_app_health_aggregates.call_args.kwargs
        assert call_kwargs["app_key"] == "__hassette__"

    async def test_hassette_app_key_accepted_on_listeners(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """GET /telemetry/app/__hassette__/listeners is accepted (200)."""
        response = await client.get("/api/telemetry/app/__hassette__/listeners")
        assert response.status_code == 200
        call_kwargs = mock_hassette.telemetry_query_service.get_listener_summary.call_args.kwargs
        assert call_kwargs["app_key"] == "__hassette__"


class TestTelemetryStatusDropCounterFallback:
    """AttributeError/RuntimeError fallback for get_drop_counters."""

    async def test_attribute_error_on_get_drop_counters_returns_zeros(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """AttributeError from get_drop_counters falls back to zero counters."""
        mock_hassette.get_drop_counters.side_effect = AttributeError("no such attribute")
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0
        assert data["dropped_shutdown"] == 0

    async def test_runtime_error_on_get_drop_counters_returns_zeros(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """RuntimeError from get_drop_counters falls back to zero counters."""
        mock_hassette.get_drop_counters.side_effect = RuntimeError("not yet initialised")
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 200
        data = response.json()
        assert data["degraded"] is False
        assert data["dropped_overflow"] == 0
        assert data["dropped_exhausted"] == 0


class TestAppHealthDbErrorFallback:
    """TelemetryUnavailableError degradation guard on the app_health endpoint."""

    async def test_telemetry_unavailable_returns_503_with_zeroed_health(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError on get_app_health_aggregates returns 503 with zero-value health."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            side_effect=TelemetryUnavailableError("disk I/O error")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0
        assert data["health_status"] == "excellent"
        assert data["handler_avg_duration"] == 0.0
        assert data["job_avg_duration"] == 0.0
        assert data["last_activity_ts"] is None

    async def test_valueerror_returns_503_with_zeroed_health(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError (wrapping closed-connection ValueError) returns 503."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            side_effect=TelemetryUnavailableError("Connection is closed")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0

    async def test_sqlite_error_triggers_503(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        """TelemetryUnavailableError (wrapping sqlite3.Error) on get_app_health_aggregates returns 503."""
        mock_hassette.telemetry_query_service.get_app_health_aggregates = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/app/my_app/health")
        assert response.status_code == 503
        data = response.json()
        assert data["error_rate"] == 0.0


class TestDashboardAppGridDbErrorFallback:
    """TelemetryUnavailableError degradation guard on dashboard_app_grid (category-C, silent-200)."""

    async def test_telemetry_unavailable_returns_200_with_empty_summaries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError on get_all_app_summaries falls back to empty summaries dict.

        The endpoint still returns 200 with manifests having zero health data.
        """
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        # Each manifest entry should still appear, but with zeroed health data
        for entry in data["apps"]:
            assert entry["total_invocations"] == 0
            assert entry["total_errors"] == 0
            assert entry["error_rate"] == 0.0

    async def test_oserror_returns_200_with_zeroed_entries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError (wrapping OSError) falls back to zeroed per-app entries."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=TelemetryUnavailableError("disk I/O error")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
        for entry in data["apps"]:
            assert entry["handler_count"] == 0
            assert entry["job_count"] == 0

    async def test_valueerror_returns_200_with_zeroed_entries(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """TelemetryUnavailableError (wrapping closed-connection ValueError) falls back to zeroed entries."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=TelemetryUnavailableError("Connection is closed")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data

    async def test_app_grid_db_error_uses_error_rate_from_empty_summary(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        """When summaries dict is empty after DB error, error_rate_from_summary returns 0.0."""
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=TelemetryUnavailableError("database is locked")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        assert response.status_code == 200
        data = response.json()
        for entry in data["apps"]:
            # total_invocations=0 and total_executions=0 → error_rate=0.0
            assert entry["error_rate"] == 0.0
            # zero-invocation apps return "excellent" (not "unknown")
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

    async def test_nonexistent_app_key_start_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/start")
        assert response.status_code == 404

    async def test_nonexistent_app_key_stop_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/stop")
        assert response.status_code == 404

    async def test_nonexistent_app_key_reload_returns_404(self, client: "AsyncClient", mock_hassette) -> None:
        """Non-existent app_key returns 404 when registry has no manifest."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None
        response = await client.post("/api/apps/unknown_app/reload")
        assert response.status_code == 404

    async def test_valid_app_key_with_dots_and_underscores_accepted(self, client: "AsyncClient") -> None:
        """app_key with dots and underscores is valid per the regex."""
        response = await client.post("/api/apps/my_app.v2/start")
        assert response.status_code == 202

    async def test_valid_app_key_128_chars_accepted(self, client: "AsyncClient") -> None:
        """app_key exactly 128 chars (1 letter + 127 more) is accepted."""
        app_key = "a" + "b" * 127
        response = await client.post(f"/api/apps/{app_key}/start")
        assert response.status_code == 202


class TestLimitParameterValidation:
    """Verify out-of-range limit parameters return 422 across all relevant endpoints."""

    async def test_events_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=0")
        assert response.status_code == 422

    async def test_events_limit_negative_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=-1")
        assert response.status_code == 422

    async def test_events_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=501")
        assert response.status_code == 422

    async def test_events_limit_at_max_accepted(self, client: "AsyncClient") -> None:
        response = await client.get("/api/events/recent?limit=500")
        assert response.status_code == 200

    async def test_logs_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=0")
        assert response.status_code == 422

    async def test_logs_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=2001")
        assert response.status_code == 422

    async def test_logs_limit_at_max_accepted(self, client: "AsyncClient") -> None:
        response = await client.get("/api/logs/recent?limit=2000")
        assert response.status_code == 200

    # Skipped — covered by TestTelemetrySessionsEndpoint.test_sessions_endpoint_limit_parameter

    async def test_listener_executions_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/listener/1/executions?limit=0")
        assert response.status_code == 422

    async def test_listener_executions_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/listener/1/executions?limit=501")
        assert response.status_code == 422

    async def test_listener_executions_limit_at_max_accepted(
        self, client: "AsyncClient", mock_hassette: MagicMock
    ) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/listener/1/executions?limit=500")
        assert response.status_code == 200

    async def test_job_executions_limit_zero_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/job/1/executions?limit=0")
        assert response.status_code == 422

    async def test_job_executions_limit_over_max_returns_422(self, client: "AsyncClient") -> None:
        response = await client.get("/api/telemetry/job/1/executions?limit=501")
        assert response.status_code == 422

    async def test_job_executions_limit_at_max_accepted(self, client: "AsyncClient", mock_hassette: MagicMock) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get("/api/telemetry/job/1/executions?limit=500")
        assert response.status_code == 200
