"""Integration tests for GET /api/apps/{app_key}/config."""

from tests.integration.conftest import make_manifest_mock


class TestAppConfigEndpoint:
    """Tests for GET /api/apps/{app_key}/config."""

    async def test_known_app_returns_config(self, client, mock_hassette) -> None:
        """Returns 200 with AppConfigResponse for a known app key."""
        manifest = make_manifest_mock(
            app_key="my_app",
            filename="my_app.py",
            class_name="MyApp",
            enabled=True,
            app_config={"instance_name": "MyApp.0", "brightness": 100},
        )
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert data["app_key"] == "my_app"
        assert data["filename"] == "my_app.py"
        assert data["class_name"] == "MyApp"
        assert data["enabled"] is True
        assert data["app_config"]["brightness"] == 100

    async def test_unknown_app_returns_404(self, client, mock_hassette) -> None:
        """Returns 404 when app_key is not in the registry."""
        mock_hassette._app_handler.registry.get_manifest.return_value = None

        response = await client.get("/api/apps/nonexistent_app/config")

        assert response.status_code == 404

    async def test_multi_instance_app_returns_list_config(self, client, mock_hassette) -> None:
        """Returns list config for a multi-instance app."""
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

        response = await client.get("/api/apps/my_app/config")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data["app_config"], list)
        assert len(data["app_config"]) == 2
        assert data["app_config"][0]["zone"] == "kitchen"
        assert data["app_config"][1]["zone"] == "bedroom"

    async def test_disabled_app_still_returns_config(self, client, mock_hassette) -> None:
        """Disabled apps still expose their config."""
        manifest = make_manifest_mock(app_key="disabled_app", enabled=False)
        mock_hassette._app_handler.registry.get_manifest.return_value = manifest

        response = await client.get("/api/apps/disabled_app/config")

        assert response.status_code == 200
        assert response.json()["enabled"] is False

    async def test_invalid_app_key_returns_400(self, client) -> None:
        """Invalid app_key format returns 400."""
        response = await client.get("/api/apps/!!invalid!!/config")

        assert response.status_code == 400
