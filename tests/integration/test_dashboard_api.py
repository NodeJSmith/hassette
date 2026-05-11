"""Integration tests for the /api/health endpoint (version, boot_issues).

Tests for the four removed overview endpoints (dashboard/kpis, dashboard/activity,
dashboard/errors, dashboard/framework-summary) were deleted as part of the
overview page removal (spec 051).
"""

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
import pytest
from httpx import ASGITransport, AsyncClient

from hassette.core.domain_models import BootIssue, SystemStatus
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app


@pytest.fixture
def stub():
    """Create a Hassette stub for health endpoint tests."""
    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
def rqs(stub):
    """Create a RuntimeQueryService wired to the stub."""
    return create_mock_runtime_query_service(stub)


@pytest.fixture
async def client(stub, rqs):  # noqa: ARG001 — rqs wired to stub as side-effect
    app = create_fastapi_app(stub)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, stub


# ---------------------------------------------------------------------------
# /api/health endpoint tests
# ---------------------------------------------------------------------------


class TestVersionInHealth:
    async def test_health_returns_version(self, client) -> None:
        """GET /api/health response includes a 'version' field."""
        ac, stub = client
        # Wire get_system_status to return a status with version
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=10.0,
                entity_count=5,
                app_count=1,
                services_running=[],
                version="0.99.0",
                boot_issues=[],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] == "0.99.0"

    async def test_health_returns_boot_issues(self, client) -> None:
        """GET /api/health response includes 'boot_issues' list."""
        ac, stub = client
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=5.0,
                entity_count=0,
                app_count=0,
                services_running=[],
                version="1.0.0",
                boot_issues=[
                    BootIssue(severity="warn", label="App blocked", detail="my_app: import error"),
                ],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "boot_issues" in data
        assert len(data["boot_issues"]) == 1
        issue = data["boot_issues"][0]
        assert issue["severity"] == "warn"
        assert issue["label"] == "App blocked"
        assert "import error" in issue["detail"]

    async def test_health_boot_issues_empty_by_default(self, client) -> None:
        """GET /api/health with no boot issues returns an empty list."""
        ac, stub = client
        stub.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=1.0,
                entity_count=0,
                app_count=0,
                services_running=[],
            )
        )
        response = await ac.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["boot_issues"] == []
