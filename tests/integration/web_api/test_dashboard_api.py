"""Integration tests for the /api/health endpoint (version, boot_issues)."""

from typing import Any
from unittest.mock import MagicMock

from httpx2 import AsyncClient

from hassette.schemas.domain_models import BootIssue, SystemStatus

from .conftest import get_json

HEALTH_PATH = "/api/health"


async def get_health_with_status(client: AsyncClient, mock_hassette, **status_fields) -> Any:
    """Wire a `SystemStatus` onto the runtime query service, then GET `/api/health`.

    Only the fields a test actually asserts on are passed; the rest keep a healthy baseline so
    the assertion reads as "given this status, the response carries these fields".
    """
    mock_hassette.runtime_query_service.get_system_status = MagicMock(
        return_value=SystemStatus(
            status="ok",
            websocket_connected=True,
            bootstrap_released=True,
            **status_fields,
        )
    )
    return await get_json(client, HEALTH_PATH)


class TestVersionInHealth:
    async def test_health_returns_version(self, client, mock_hassette) -> None:
        """GET /api/health response includes a 'version' field."""
        data = await get_health_with_status(
            client, mock_hassette, uptime_seconds=10.0, entity_count=5, app_count=1, version="0.99.0", boot_issues=[]
        )

        assert "version" in data
        assert data["version"] == "0.99.0"

    async def test_health_returns_boot_issues(self, client, mock_hassette) -> None:
        """GET /api/health response includes 'boot_issues' list."""
        data = await get_health_with_status(
            client,
            mock_hassette,
            uptime_seconds=5.0,
            entity_count=0,
            app_count=0,
            version="1.0.0",
            boot_issues=[BootIssue(severity="warn", label="App blocked", detail="my_app: import error")],
        )

        assert "boot_issues" in data
        assert len(data["boot_issues"]) == 1
        issue = data["boot_issues"][0]
        assert issue["severity"] == "warn"
        assert issue["label"] == "App blocked"
        assert "import error" in issue["detail"]

    async def test_health_boot_issues_empty_by_default(self, client, mock_hassette) -> None:
        """GET /api/health with no boot issues returns an empty list."""
        data = await get_health_with_status(client, mock_hassette, uptime_seconds=1.0, entity_count=0, app_count=0)

        assert data["boot_issues"] == []
