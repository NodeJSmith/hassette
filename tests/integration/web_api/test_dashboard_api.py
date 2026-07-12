"""Integration tests for the /api/health endpoint (version, boot_issues)."""

from unittest.mock import MagicMock

from hassette.schemas.domain_models import BootIssue, SystemStatus


class TestVersionInHealth:
    async def test_health_returns_version(self, client, mock_hassette) -> None:
        """GET /api/health response includes a 'version' field."""
        mock_hassette.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=10.0,
                entity_count=5,
                app_count=1,
                version="0.99.0",
                boot_issues=[],
            )
        )
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert data["version"] == "0.99.0"

    async def test_health_returns_boot_issues(self, client, mock_hassette) -> None:
        """GET /api/health response includes 'boot_issues' list."""
        mock_hassette.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=5.0,
                entity_count=0,
                app_count=0,
                version="1.0.0",
                boot_issues=[
                    BootIssue(severity="warn", label="App blocked", detail="my_app: import error"),
                ],
            )
        )
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "boot_issues" in data
        assert len(data["boot_issues"]) == 1
        issue = data["boot_issues"][0]
        assert issue["severity"] == "warn"
        assert issue["label"] == "App blocked"
        assert "import error" in issue["detail"]

    async def test_health_boot_issues_empty_by_default(self, client, mock_hassette) -> None:
        """GET /api/health with no boot issues returns an empty list."""
        mock_hassette.runtime_query_service.get_system_status = MagicMock(
            return_value=SystemStatus(
                status="ok",
                websocket_connected=True,
                uptime_seconds=1.0,
                entity_count=0,
                app_count=0,
            )
        )
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["boot_issues"] == []
