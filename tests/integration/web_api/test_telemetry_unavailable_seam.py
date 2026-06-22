"""Tests for the TelemetryUnavailableError storage→domain translation seam (#1108b / #1114).

Three behaviors:

(a) A storage error translated to TelemetryUnavailableError surfaces correctly: the route
    still returns its prior 503/200 outcome unchanged.
(b) Footgun-fixed: a non-DB ValueError raised in a handler body now propagates as HTTP 500,
    not a swallowed 503 (the cluster's one intended behavior change).
(c) A forced storage error in get_all_app_summaries still degrades dashboard_app_grid to
    200-partial, not 500.
"""

from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient

from hassette.exceptions import TelemetryUnavailableError
from hassette.web.app import create_fastapi_app


class TestTranslationSurfaces503:
    """(a) TelemetryUnavailableError from service → same 503 the route gave before."""

    async def test_storage_error_gives_503_on_logs_endpoint(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
    ) -> None:
        """A TelemetryUnavailableError from the service still yields 503 on /api/logs/recent."""
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(
            side_effect=TelemetryUnavailableError("simulated db failure")
        )
        response = await client.get("/api/logs/recent")
        assert response.status_code == 503

    async def test_storage_error_gives_503_on_telemetry_status(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
    ) -> None:
        """A TelemetryUnavailableError from check_health still yields 503 on /api/telemetry/status."""
        mock_hassette.telemetry_query_service.check_health = AsyncMock(side_effect=TelemetryUnavailableError("db down"))
        response = await client.get("/api/telemetry/status")
        assert response.status_code == 503
        data = response.json()
        assert data["degraded"] is True


class TestFootgunFixed:
    """(b) A non-DB ValueError in a handler body now returns HTTP 500, not a swallowed 503."""

    async def test_non_db_value_error_in_handler_returns_500(
        self,
        mock_hassette: MagicMock,
    ) -> None:
        """ValueError raised by application logic (not the DB) must produce HTTP 500.

        Before #1108b, db_degrades_to caught the broad DB_ERRORS tuple including ValueError,
        so any ValueError inside the 'with' block silently became a 503.
        After #1108b, db_degrades_to catches only TelemetryUnavailableError, so a
        non-DB ValueError propagates to FastAPI's default 500 handler.

        Uses raise_app_exceptions=False so the 500 is returned as a response rather than
        re-raised in the test process.
        """
        mock_hassette.telemetry_query_service.get_log_records = AsyncMock(
            side_effect=ValueError("not a db error — bad app logic")
        )
        app = create_fastapi_app(mock_hassette)
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/logs/recent")
        # Must be 500 (unhandled), NOT 503 (swallowed as "db degraded")
        assert response.status_code == 500


class TestDashboardAppGridDegrades:
    """(c) A storage error in get_all_app_summaries still degrades to 200-partial, not 500."""

    async def test_storage_error_in_get_all_app_summaries_yields_200_partial(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
    ) -> None:
        """get_all_app_summaries raising TelemetryUnavailableError must not produce a 500.

        This endpoint is category-C (silent-200): it has a non-DB spine from
        runtime.get_all_manifests_snapshot(). DB failure returns partial data with HTTP 200.
        """
        mock_hassette.telemetry_query_service.get_all_app_summaries = AsyncMock(
            side_effect=TelemetryUnavailableError("db unavailable during summary fetch")
        )
        response = await client.get("/api/telemetry/dashboard/app-grid")
        # Must be 200 (partial), not 500 (unhandled) — category-C site contract
        assert response.status_code == 200
        data = response.json()
        assert "apps" in data
