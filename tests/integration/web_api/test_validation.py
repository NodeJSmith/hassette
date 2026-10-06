"""Integration tests for validation, error guards, and edge cases in the web API."""

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from hassette.schemas.query_constants import MAX_QUERY_LIMIT
from hassette.web.routes.logs import RECENT_LOGS_LIMIT_CAP

from .conftest import APP_GRID_PATH, TELEMETRY_STATUS_PATH, get_json, seed_grid_apps, telemetry_error

if TYPE_CHECKING:
    from httpx2 import AsyncClient

# Each entry is a storage failure an optional enrichment query must absorb, keeping the response
# at 200. The message differs only to document which underlying error the service wrapped.
WRAPPED_STORAGE_ERRORS = [
    pytest.param("database is locked", id="sqlite-error"),
    pytest.param("disk I/O error", id="oserror"),
    pytest.param("Connection is closed", id="closed-connection"),
]


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

    @pytest.mark.parametrize(
        "error",
        [AttributeError("no such attribute"), RuntimeError("not yet initialised")],
        ids=["attribute-error", "runtime-error"],
    )
    async def test_get_filtered_count_failure_returns_zero(
        self, client: "AsyncClient", mock_hassette: MagicMock, error: Exception
    ) -> None:
        """A command_executor.get_filtered_count() failure falls back to zero without degrading the route."""
        mock_hassette.command_executor.get_filtered_count.side_effect = error

        data = await get_json(client, TELEMETRY_STATUS_PATH)

        assert data["degraded"] is False
        assert data["dropped_filtered"] == 0


class TestAppGridDbErrorFallback:
    """TelemetryUnavailableError degradation guard on app_grid's optional enrichment query.

    The enrichment query failing must leave the response at 200 with every entry's ``stats`` null --
    the DB spine query succeeds independently, so every manifest entry still appears.
    """

    @pytest.mark.parametrize("message", WRAPPED_STORAGE_ERRORS)
    async def test_telemetry_unavailable_returns_200_with_null_stats(
        self, client: "AsyncClient", mock_hassette: MagicMock, message: str
    ) -> None:
        """get_all_app_summaries raising nulls each row's stats rather than reading as zero, healthy data."""
        seed_grid_apps(mock_hassette, "a", "b")
        mock_hassette.telemetry_query_service.get_all_app_summaries = telemetry_error(message)

        data = await get_json(client, APP_GRID_PATH)

        assert len(data["apps"]) == 2
        assert all(entry["activity"]["stats"] is None for entry in data["apps"])


class TestAppKeyValidation:
    """Verify that invalid app_key values are rejected with 400 on management routes.

    The validation is performed by _validate_app_key() in apps.py using the regex
    ``^[a-zA-Z_][a-zA-Z0-9_.]{0,127}$``. It raises ``WebApiError(ProblemCode.INVALID_APP_KEY)``, which
    answers a 400 problem+json body with code ``invalid_app_key`` rather than a 422 validation error.
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
            ("/api/logs/recent", RECENT_LOGS_LIMIT_CAP + 1),
            ("/api/telemetry/listener/1/executions", 0),
            ("/api/telemetry/listener/1/executions", MAX_QUERY_LIMIT + 1),
            ("/api/telemetry/job/1/executions", 0),
            ("/api/telemetry/job/1/executions", MAX_QUERY_LIMIT + 1),
        ],
    )
    async def test_out_of_range_limit_returns_422(self, client: "AsyncClient", path: str, limit: int) -> None:
        response = await client.get(f"{path}?limit={limit}")
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("path", "limit"),
        [
            ("/api/logs/recent", RECENT_LOGS_LIMIT_CAP),
            ("/api/telemetry/listener/1/executions", MAX_QUERY_LIMIT),
            ("/api/telemetry/job/1/executions", MAX_QUERY_LIMIT),
        ],
    )
    async def test_limit_at_max_accepted(
        self, client: "AsyncClient", mock_hassette: MagicMock, path: str, limit: int
    ) -> None:
        mock_hassette.telemetry_query_service.get_executions = AsyncMock(return_value=[])
        response = await client.get(f"{path}?limit={limit}")
        assert response.status_code == 200
