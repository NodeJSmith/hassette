"""Tests for the TelemetryUnavailableError storage→domain translation seam (#1108b / #1114).

Three behaviors:

(a) A storage error translated to TelemetryUnavailableError surfaces as a 503.
(b) A non-DB ValueError raised in a handler body propagates as HTTP 500, not a 503.
(c) A forced storage error in get_all_app_summaries still degrades dashboard_app_grid to
    200-partial, not 500.

The problem body each data route answers with is pinned per route in ``test_problem_details.py``.
"""

from unittest.mock import AsyncMock, MagicMock

from httpx2 import ASGITransport, AsyncClient

from hassette.web.app import create_fastapi_app
from tests.support.web_manifest_helpers import make_manifest_db_row

from .conftest import APP_GRID_PATH, TELEMETRY_STATUS_PATH, get_json, telemetry_error


class TestTranslationSurfaces503:
    """(a) TelemetryUnavailableError from the service surfaces as a 503."""

    async def test_storage_error_gives_503_on_logs_endpoint(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
    ) -> None:
        """A TelemetryUnavailableError from the service still yields 503 on /api/logs/recent."""
        mock_hassette.telemetry_query_service.get_log_records = telemetry_error("simulated db failure")

        await get_json(client, "/api/logs/recent", expect_status=503)

    async def test_storage_error_gives_503_on_telemetry_status(
        self,
        client: "AsyncClient",
        mock_hassette: MagicMock,
    ) -> None:
        """A TelemetryUnavailableError from check_health still yields 503 on /api/telemetry/status."""
        mock_hassette.telemetry_query_service.check_health = telemetry_error("db down")

        data = await get_json(client, TELEMETRY_STATUS_PATH, expect_status=503)

        assert data["degraded"] is True


class TestFootgunFixed:
    """(b) A non-DB ValueError in a handler body returns HTTP 500, not a 503."""

    async def test_non_db_value_error_in_handler_returns_500(
        self,
        mock_hassette: MagicMock,
    ) -> None:
        """ValueError raised by application logic (not the DB) must produce HTTP 500.

        Only TelemetryUnavailableError maps to 503, so a non-DB ValueError reaches the
        unhandled-exception handler instead.

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

        This is an optional enrichment query: the required spine query
        (get_all_app_manifests + overlay_runtime_state()) succeeds independently, and this
        one enrichment failure degrades to zeroed stats while the response stays 200.
        """
        mock_hassette.telemetry_query_service.get_all_app_manifests = AsyncMock(
            return_value=[make_manifest_db_row(app_key="my_app")]
        )
        mock_hassette.telemetry_query_service.get_all_app_summaries = telemetry_error(
            "db unavailable during summary fetch"
        )

        # Must be 200 (partial), not 503 or 500 — an optional query never fails the request
        data = await get_json(client, APP_GRID_PATH)

        assert "apps" in data
        assert len(data["apps"]) == 1
        assert data["apps"][0]["total_invocations"] == 0
