"""Integration tests for GET /api/apps/{app_key}/config."""

import pytest
from httpx import ASGITransport, AsyncClient

from hassette.test_utils.web_mocks import create_hassette_stub
from hassette.web.app import create_fastapi_app

from .conftest import make_manifest_mock


@pytest.fixture
def mock_hassette():
    return create_hassette_stub(run_web_ui=False)


@pytest.fixture
async def client(mock_hassette):
    app = create_fastapi_app(mock_hassette)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, mock_hassette


class TestAppConfigEndpoint:
    """Tests for GET /api/apps/{app_key}/config."""

    async def test_known_app_returns_config(self, client) -> None:
        """Returns 200 with AppConfigResponse for a known app key."""
        ac, mock_hassette = client
        manifest = make_manifest_mock(
            app_key="my_app",
            filename="my_app.py",
            class_name="MyApp",
            enabled=True,
            app_config={"instance_name": "MyApp.0", "brightness": 100},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest

        response = await ac.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["filename"] == "my_app.py"
        assert data["class_name"] == "MyApp"
        assert data["enabled"] is True
        assert data["app_config"]["brightness"] == 100

    async def test_unknown_app_returns_404(self, client) -> None:
        """Returns 404 when app_key is not in the registry."""
        ac, mock_hassette = client
        mock_hassette._app_handler.registry.get_manifest.return_value = None

        response = await ac.get("/api/apps/nonexistent_app/config")

        assert response.status_code == 404

    async def test_multi_instance_app_returns_list_config(self, client) -> None:
        """Returns list config for a multi-instance app."""
        ac, mock_hassette = client
        list_config = [
            {"instance_name": "MyApp.0", "zone": "kitchen"},
            {"instance_name": "MyApp.1", "zone": "bedroom"},
        ]
        manifest = make_manifest_mock(
            app_key="my_app",
            class_name="MyApp",
            app_config=list_config,
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest

        response = await ac.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["app_config"], list)
        assert len(data["app_config"]) == 2
        assert data["app_config"][0]["zone"] == "kitchen"
        assert data["app_config"][1]["zone"] == "bedroom"

    async def test_disabled_app_still_returns_config(self, client) -> None:
        """Disabled apps still expose their config."""
        ac, mock_hassette = client
        manifest = make_manifest_mock(app_key="disabled_app", enabled=False)
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest

        response = await ac.get("/api/apps/disabled_app/config")

        assert response.status_code == 200
        assert response.json()["enabled"] is False

    async def test_invalid_app_key_returns_400(self, client) -> None:
        """Invalid app_key format returns 400."""
        ac, _mock = client

        response = await ac.get("/api/apps/!!invalid!!/config")

        assert response.status_code == 400
