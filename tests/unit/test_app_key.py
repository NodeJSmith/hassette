"""Tests for App.app_key property."""

from unittest.mock import Mock, patch

from hassette.app.app import App


class TestAppKey:
    def test_app_key_delegates_to_manifest(self) -> None:
        """App.app_key should return app_manifest.app_key."""
        app = App.__new__(App)
        manifest = Mock()
        manifest.app_key = "my_kitchen_lights"

        with patch.object(App, "app_manifest", manifest):
            assert app.app_key == "my_kitchen_lights"
