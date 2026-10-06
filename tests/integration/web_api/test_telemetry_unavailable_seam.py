"""Tests for the TelemetryUnavailableError storage→domain translation seam (#1108b / #1114).

- Only TelemetryUnavailableError maps to 503: a non-DB ValueError raised in a handler body
  propagates as HTTP 500.

The app grid's degradation to 200-partial on an enrichment storage error is pinned in
``test_validation.py`` (``TestAppGridDbErrorFallback``) and ``test_app_grid.py``.

The ``telemetry_unavailable`` problem body each data route answers with, and the probe's status
body, are pinned per route in ``test_problem_details.py``.
"""

from unittest.mock import AsyncMock, MagicMock

from httpx2 import ASGITransport, AsyncClient

from hassette.web.app import create_fastapi_app


class TestNonTelemetryErrorsStay500:
    """A non-DB ValueError in a handler body returns HTTP 500, not a 503."""

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
