"""Integration tests for auto-detect functionality with HassetteConfig.

Split out of `test_autodetect_apps.py` (see design/specs/100-decompose-oversized-test-files).
Complements `test_autodetect_apps.py` (TestAutoDetectAppsCurrDir, TestAutoDetectApps) and
`test_validate_apps.py` (TestValidateApps).
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.testing._harness import TEST_TOKEN
from tests.support.helpers import write_app


class TestAutoDetectIntegration:
    """Integration tests for auto-detect functionality with HassetteConfig."""

    @pytest.fixture(autouse=True)
    def setup(self, test_config: HassetteConfig) -> Iterator[None]:
        with context.use_hassette_config(test_config):
            yield

    def test_hassette_config_autodetect_enabled_by_default(self, tmp_path: Path) -> None:
        """Test that autodetect_apps is enabled by default in HassetteConfig."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "test_app.py",
            """
            from hassette import App, AppConfig

            class TestApp(App[AppConfig]): ...
            """,
        )

        # Create config with the temp app directory
        config = HassetteConfig(token=TEST_TOKEN, apps={"directory": app_dir}, cli_parse_args=False)
        config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should auto-detect the app
        assert "apps.test_app.TestApp" in result, "Expected to find 'apps.test_app.TestApp' in detected apps"
        manifest = result["apps.test_app.TestApp"]
        assert manifest.filename == "test_app.py", f"Expected filename to be 'test_app.py', got {manifest.filename}"
        assert manifest.class_name == "TestApp", f"Expected class_name to be 'TestApp', got {manifest.class_name}"
        assert manifest.enabled is True, f"Expected enabled to be True, got {manifest.enabled}"

    def test_hassette_config_autodetect_can_be_disabled(self, tmp_path: Path) -> None:
        """Test that autodetect_apps can be disabled in HassetteConfig."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "test_app.py",
            """
            from hassette import App, AppConfig

            class TestApp(App[AppConfig]): ...
            """,
        )

        # Create config with auto-detect disabled
        config = HassetteConfig(
            token=TEST_TOKEN,
            apps={"directory": app_dir, "autodetect": False},
            cli_parse_args=False,
        )

        # `autodetect` is only evaluated inside set_validated_app_manifests(), so the assertion
        # has to run after it — and against `manifests`, which is what discovery populates.
        config.set_validated_app_manifests()

        # Should not auto-detect any apps (no manual apps configured either)
        assert len(config.apps.manifests) == 0, f"Expected 0 manifests, got {sorted(config.apps.manifests)}"

    @pytest.mark.parametrize("ext", [".py", ""])
    def test_defined_filename_without_extension_is_handled(self, tmp_path: Path, ext: str) -> None:
        """If we define something in hassette.toml but forget the .py extension, we shouldn't load it twice.

        We handle the missing .py in the AppManifest, but we need to make sure that the auto-detect
        logic also handles this case correctly.

        """
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "priority_app.py",
            """
            from hassette import App, AppConfig

            class MyConfig(AppConfig):
                custom: str = "auto-app"

            class AutoDetectedApp(App[AppConfig]): ...
            """,
        )

        # Create config with manual app configuration that conflicts
        config = HassetteConfig(
            token=TEST_TOKEN,
            apps={
                "directory": app_dir,
                "apps": {
                    "AutoDetectedApp": {
                        "filename": f"priority_app{ext}",
                        "class_name": "AutoDetectedApp",
                        "enabled": True,  # Different from auto-detect default
                        "config": {"custom": "value"},
                    }
                },
            },
            cli_parse_args=False,
        )

        config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should have the manual configuration, not auto-detected
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "AutoDetectedApp" in result, "Expected to find 'priority_app.AutoDetectedApp' in detected apps"
        manifest = result["AutoDetectedApp"]
        assert manifest.enabled is True, f"Expected enabled to be True, got {manifest.enabled}"
        assert manifest.app_config[0]["custom"] == "value", (
            f"Expected custom config to be 'value', got {manifest.app_config[0]['custom']}"
        )

    def test_hassette_config_manual_apps_take_precedence(self, tmp_path: Path) -> None:
        """Test that manually configured apps take precedence over auto-detected ones."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "priority_app.py",
            """
            from hassette import App, AppConfig

            class AutoDetectedApp(App[AppConfig]): ...
            """,
        )

        # Create config with manual app configuration that conflicts
        config = HassetteConfig(
            token=TEST_TOKEN,
            apps={
                "directory": app_dir,
                "apps": {
                    "priority_app.AutoDetectedApp": {
                        "filename": "priority_app.py",
                        "class_name": "AutoDetectedApp",
                        "enabled": False,  # Different from auto-detect default
                        "config": {"custom": "value"},
                    }
                },
            },
            cli_parse_args=False,
        )

        config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should have the manual configuration, not auto-detected
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "priority_app.AutoDetectedApp" in result, (
            "Expected to find 'priority_app.AutoDetectedApp' in detected apps"
        )
        manifest = result["priority_app.AutoDetectedApp"]
        assert manifest.enabled is False, f"Expected enabled to be False, got {manifest.enabled}"
        assert manifest.app_config[0]["custom"] == "value", (
            f"Expected custom config to be 'value', got {manifest.app_config[0]['custom']}"
        )

    def test_hassette_config_combines_manual_and_autodetected(self, tmp_path: Path) -> None:
        """Test that HassetteConfig combines manual and auto-detected apps correctly."""
        # Create a temporary app directory with multiple apps
        app_dir = tmp_path / "apps"

        # Auto-detected app
        write_app(
            app_dir,
            "auto_app.py",
            """
            from hassette import App, AppConfig

            class AutoApp(App[AppConfig]): ...
            """,
        )

        # Manually configured app
        write_app(
            app_dir,
            "manual_app.py",
            """
            from hassette import App, AppConfig

            class ManualApp(App[AppConfig]): ...
            """,
        )

        # Create config with one manual app
        config = HassetteConfig(
            token=TEST_TOKEN,
            apps={
                "directory": app_dir,
                "apps": {
                    "manual_app": {
                        "filename": "manual_app.py",
                        "class_name": "ManualApp",
                        "config": {"manual": True},
                    }
                },
            },
            cli_parse_args=False,
        )

        config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should have both manual and auto-detected apps
        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "manual_app" in result, "Expected to find 'manual_app' in detected apps"
        assert "apps.auto_app.AutoApp" in result, "Expected to find 'apps.auto_app.AutoApp' in detected apps"

        # Manual app should preserve config
        manual_manifest = result["manual_app"]
        assert manual_manifest.app_config[0]["manual"] is True, (
            f"Expected manual config to be True, got {manual_manifest.app_config[0]['manual']}"
        )

        # Auto-detected app should have default config
        auto_manifest = result["apps.auto_app.AutoApp"]
        assert auto_manifest.enabled is True, f"Expected enabled to be True, got {auto_manifest.enabled}"
