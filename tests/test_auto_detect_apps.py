"""Tests for auto-detect apps functionality."""

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from hassette.config.app_manifest import AppManifest
from hassette.config.core_config import HassetteConfig, auto_detect_app_manifests, validate_apps


class TestAutoDetectAppManifests:
    """Test the auto_detect_app_manifests function."""

    def test_auto_detect_simple_app(self, tmp_path: Path):
        """Test auto-detection of a simple app in the root directory."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create a simple app file
        app_file = app_dir / "simple_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class SimpleAppConfig(AppConfig):
                message: str = "Hello"

            class SimpleApp(App[SimpleAppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        assert len(result) == 1
        assert "simple_app.SimpleApp" in result

        manifest = result["simple_app.SimpleApp"]
        assert manifest.filename == "simple_app.py", f"Expected 'simple_app.py', got '{manifest.filename}'"
        assert manifest.class_name == "SimpleApp", f"Expected 'SimpleApp', got '{manifest.class_name}'"
        assert manifest.app_dir == app_dir, f"Expected '{app_dir}', got '{manifest.app_dir}'"
        assert manifest.app_key == "simple_app.SimpleApp", f"Expected 'simple_app.SimpleApp', got '{manifest.app_key}'"
        assert manifest.enabled is True, f"Expected 'True', got '{manifest.enabled}'"

    def test_auto_detect_sync_app(self, tmp_path: Path):
        """Test auto-detection of a sync app."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create a sync app file
        app_file = app_dir / "sync_app.py"
        app_file.write_text(
            dedent("""
            from hassette import AppSync, AppConfig

            class SyncAppConfig(AppConfig):
                interval: int = 60

            class MySyncApp(AppSync[SyncAppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        assert len(result) == 1
        assert "sync_app.MySyncApp" in result, "Expected to find 'sync_app.MySyncApp' in detected apps"

        manifest = result["sync_app.MySyncApp"]
        assert manifest.filename == "sync_app.py", f"Expected 'sync_app.py', got '{manifest.filename}'"
        assert manifest.class_name == "MySyncApp", f"Expected 'MySyncApp', got '{manifest.class_name}'"

    def test_auto_detect_multiple_apps_in_file(self, tmp_path: Path):
        """Test auto-detection when multiple app classes exist in one file."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create a file with multiple app classes
        app_file = app_dir / "multi_apps.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppSync, AppConfig

            class SharedConfig(AppConfig):
                name: str = "test"

            class FirstApp(App[SharedConfig]): ...

            class SecondApp(AppSync[SharedConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "multi_apps.FirstApp" in result, "Expected to find 'multi_apps.FirstApp' in detected apps"
        assert "multi_apps.SecondApp" in result, "Expected to find 'multi_apps.SecondApp' in detected apps"

        first_manifest = result["multi_apps.FirstApp"]
        assert first_manifest.class_name == "FirstApp", f"Expected 'FirstApp', got '{first_manifest.class_name}'"

        second_manifest = result["multi_apps.SecondApp"]
        assert second_manifest.class_name == "SecondApp", f"Expected 'SecondApp', got '{second_manifest.class_name}'"

    def test_auto_detect_nested_directory(self, tmp_path: Path):
        """Test auto-detection of apps in nested directories."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create nested directory structure
        notifications_dir = app_dir / "notifications"
        notifications_dir.mkdir()

        app_file = notifications_dir / "email_notifier.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class EmailConfig(AppConfig):
                smtp_server: str = "localhost"

            class EmailNotifier(App[EmailConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "notifications.email_notifier.EmailNotifier" in result, (
            "Expected to find 'notifications.email_notifier.EmailNotifier' in detected apps"
        )

        manifest = result["notifications.email_notifier.EmailNotifier"]
        assert manifest.filename == "email_notifier.py", f"Expected 'email_notifier.py', got '{manifest.filename}'"
        assert manifest.class_name == "EmailNotifier", f"Expected 'EmailNotifier', got '{manifest.class_name}'"
        assert manifest.app_key == "notifications.email_notifier.EmailNotifier", (
            f"Expected 'notifications.email_notifier.EmailNotifier', got '{manifest.app_key}'"
        )

    def test_auto_detect_skips_known_paths(self, tmp_path: Path):
        """Test that auto-detection skips already configured apps."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "configured_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class ConfiguredApp(App[AppConfig]): ...
        """)
        )

        # Include this file in known_paths
        known_paths = {app_file.resolve()}
        result = auto_detect_app_manifests(app_dir, known_paths)

        assert len(result) == 0, "Expected no apps to be detected since the only app is in known_paths"

    def test_auto_detect_ignores_base_classes(self, tmp_path: Path):
        """Test that auto-detection ignores the base App and AppSync classes."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "base_classes.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppSync, AppConfig

            # These should not be detected
            App = App
            AppSync = AppSync

            class RealApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        # Should only find RealApp, not App or AppSync
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "base_classes.RealApp" in result, "Expected to find 'base_classes.RealApp' in detected apps"

    def test_auto_detect_ignores_imported_classes(self, tmp_path: Path):
        """Test that auto-detection ignores classes imported from other modules."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create a module with an app class
        module_file = app_dir / "my_module.py"
        module_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class ModuleApp(App[AppConfig]): ...
        """)
        )

        # Create another file that imports the class
        import_file = app_dir / "importer.py"
        import_file.write_text(
            dedent("""
            from my_module import ModuleApp
            from hassette import App, AppConfig

            class LocalApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        # Should find both apps, but each in their own module
        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "my_module.ModuleApp" in result, "Expected to find 'my_module.ModuleApp' in detected apps"
        assert "importer.LocalApp" in result, "Expected to find 'importer.LocalApp' in detected apps"
        # ModuleApp should NOT be detected in importer.py
        assert "importer.ModuleApp" not in result, "Did not expect to find 'importer.ModuleApp' in detected apps"

    def test_auto_detect_handles_import_errors(self, tmp_path: Path):
        """Test that auto-detection gracefully handles files with import errors."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Create a file with import errors
        bad_file = app_dir / "broken_app.py"
        bad_file.write_text(
            dedent("""
            from nonexistent_module import SomethingThatDoesntExist
            from hassette import App, AppConfig

            class BrokenApp(App[AppConfig]): ...
        """)
        )

        # Create a good file
        good_file = app_dir / "good_app.py"
        good_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class GoodApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        # Should only find the good app, not the broken one - this is the key functional test
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "good_app.GoodApp" in result, "Expected to find 'good_app.GoodApp' in detected apps"
        assert "broken_app.BrokenApp" not in result, "Did not expect to find 'broken_app.BrokenApp' in detected apps"

        # Verify the detected app has correct properties
        good_manifest = result["good_app.GoodApp"]
        assert good_manifest.filename == "good_app.py", f"Expected 'good_app.py', got '{good_manifest.filename}'"
        assert good_manifest.class_name == "GoodApp", f"Expected 'GoodApp', got '{good_manifest.class_name}'"

    def test_auto_detect_ignores_non_app_classes(self, tmp_path: Path):
        """Test that auto-detection ignores classes that don't inherit from App/AppSync."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "mixed_classes.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class RegularClass:
                pass

            class MyService:
                def do_something(self):
                    pass

            class ActualApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = auto_detect_app_manifests(app_dir, known_paths)

        # Should only find the actual app class
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "mixed_classes.ActualApp" in result, "Expected to find 'mixed_classes.ActualApp' in detected apps"


class TestValidateApps:
    """Test the validate_apps function."""

    def test_validate_apps_sets_app_dir(self):
        """Test that validate_apps sets app_dir for apps that don't have it."""
        app_dir = Path("/test/apps")
        values = {
            "my_app": {
                "filename": "my_app.py",
                "class_name": "MyApp",
            }
        }

        result = validate_apps(values, app_dir, auto_detect=False)

        assert result["my_app"]["app_dir"] == app_dir, (
            f"Expected app_dir to be {app_dir}, got {result['my_app']['app_dir']}"
        )
        assert result["my_app"]["app_key"] == "my_app", (
            f"Expected app_key to be 'my_app', got {result['my_app']['app_key']}"
        )

    def test_validate_apps_preserves_existing_app_dir(self):
        """Test that validate_apps preserves existing app_dir values."""
        app_dir = Path("/test/apps")
        custom_dir = Path("/custom/location")

        values = {
            "my_app": {
                "filename": "my_app.py",
                "class_name": "MyApp",
                "app_dir": custom_dir,
            }
        }

        result = validate_apps(values, app_dir, auto_detect=False)

        assert result["my_app"]["app_dir"] == custom_dir, (
            f"Expected app_dir to be {custom_dir}, got {result['my_app']['app_dir']}"
        )

    def test_validate_apps_removes_invalid_apps(self):
        """Test that validate_apps removes apps missing required keys."""
        app_dir = Path("/test/apps")
        values = {
            "valid_app": {
                "filename": "valid.py",
                "class_name": "ValidApp",
            },
            "missing_filename": {
                "class_name": "MissingFilename",
            },
            "missing_class_name": {
                "filename": "missing_class.py",
            },
            "missing_both": {
                "some_config": "value",
            },
        }

        result = validate_apps(values, app_dir, auto_detect=False)

        # Only valid_app should remain - this is the important functional test
        assert len(result) == 1, f"Expected 1 valid app, got {len(result)}"
        assert "valid_app" in result, "Expected to find 'valid_app' in detected apps"
        assert "missing_filename" not in result, "Did not expect to find 'missing_filename' in detected apps"
        assert "missing_class_name" not in result, "Did not expect to find 'missing_class_name' in detected apps"
        assert "missing_both" not in result, "Did not expect to find 'missing_both' in detected apps"

        # The valid app should have the app_dir and app_key set
        assert result["valid_app"]["app_dir"] == app_dir, (
            f"Expected app_dir to be {app_dir}, got {result['valid_app']['app_dir']}"
        )
        assert result["valid_app"]["app_key"] == "valid_app", (
            f"Expected app_key to be 'valid_app', got {result['valid_app']['app_key']}"
        )

    def test_validate_apps_skips_non_dict_values(self):
        """Test that validate_apps skips non-dict values."""
        app_dir = Path("/test/apps")
        values = {
            "valid_app": {
                "filename": "valid.py",
                "class_name": "ValidApp",
            },
            "string_value": "not a dict",
            "list_value": ["also", "not", "dict"],
            "none_value": None,
        }

        result = validate_apps(values, app_dir, auto_detect=False)

        # Should preserve all values, but only process the dict
        assert len(result) == 4, f"Expected 4 values, got {len(result)}"
        assert result["valid_app"]["app_dir"] == app_dir, (
            f"Expected app_dir to be {app_dir}, got {result['valid_app']['app_dir']}"
        )
        assert result["string_value"] == "not a dict", (
            f"Expected string_value to be 'not a dict', got {result['string_value']}"
        )
        assert result["list_value"] == ["also", "not", "dict"], (
            f"Expected list_value to be ['also', 'not', 'dict'], got {result['list_value']}"
        )
        assert result["none_value"] is None, f"Expected none_value to be None, got {result['none_value']}"

    @patch("hassette.config.core_config.auto_detect_app_manifests")
    def test_validate_apps_calls_auto_detect(self, mock_auto_detect):
        """Test that validate_apps calls auto_detect_app_manifests when auto_detect=True."""
        app_dir = Path("/test/apps")
        values = {
            "manual_app": {
                "filename": "manual.py",
                "class_name": "ManualApp",
            }
        }

        # Mock the auto-detection to return a detected app
        mock_manifest = AppManifest(
            filename="auto.py",
            class_name="AutoApp",
            app_dir=app_dir,
            app_key="auto.AutoApp",
            enabled=True,
        )
        mock_auto_detect.return_value = {"auto.AutoApp": mock_manifest}

        result = validate_apps(values, app_dir, auto_detect=True)

        # Should have both manual and auto-detected apps
        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "manual_app" in result, "Expected to find 'manual_app' in detected apps"
        assert "auto.AutoApp" in result, "Expected to find 'auto.AutoApp' in detected apps"

        # Check that auto_detect_app_manifests was called with correct parameters
        mock_auto_detect.assert_called_once()
        args, _ = mock_auto_detect.call_args
        assert args[0] == app_dir, f"Expected app_dir to be {app_dir}, got {args[0]}"
        # Should include the path of the manual app in known_paths
        known_paths = args[1]
        expected_path = (app_dir / "manual.py").resolve()
        assert expected_path in known_paths, f"Expected known_paths to include {expected_path}, got {known_paths}"

    @patch("hassette.config.core_config.auto_detect_app_manifests")
    def test_validate_apps_skips_conflicting_auto_detected(self, mock_auto_detect, caplog):
        """Test that validate_apps skips auto-detected apps that conflict with manual ones."""
        import logging

        caplog.set_level(logging.INFO, logger="hassette.config.core_config")

        app_dir = Path("/test/apps")
        values = {
            "my_app": {
                "filename": "my_app.py",
                "class_name": "MyApp",
            }
        }

        # Mock auto-detection to return an app with the same key
        mock_manifest = AppManifest(
            filename="my_app.py",
            class_name="MyApp",
            app_dir=app_dir,
            app_key="my_app",
            enabled=True,
        )
        mock_auto_detect.return_value = {"my_app": mock_manifest}

        result = validate_apps(values, app_dir, auto_detect=True)

        # Should only have the manual app, not the auto-detected one
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "my_app" in result, "Expected to find 'my_app' in detected apps"
        # Should be the original manual config, not the auto-detected one
        assert result["my_app"]["filename"] == "my_app.py", (
            f"Expected filename to be 'my_app.py', got {result['my_app']['filename']}"
        )
        assert result["my_app"]["class_name"] == "MyApp", (
            f"Expected class_name to be 'MyApp', got {result['my_app']['class_name']}"
        )

        # The behavior is that auto-detected apps with conflicting keys are simply not added
        # Let's verify that auto_detect_app_manifests was called and the result is correct
        mock_auto_detect.assert_called_once()
        # The important thing is that the result only contains the manual app

    def test_validate_apps_returns_early_if_no_app_dir(self):
        """Test that validate_apps returns early if app_dir is None."""
        values = {
            "my_app": {
                "filename": "my_app.py",
                "class_name": "MyApp",
            }
        }

        result = validate_apps(values, None, auto_detect=True)

        # Should return the input unchanged (except for removing invalid apps)
        assert result == values, "Expected validate_apps to return input unchanged when app_dir is None"

    def test_validate_apps_skips_auto_detect_when_disabled(self):
        """Test that validate_apps skips auto-detection when auto_detect=False."""
        app_dir = Path("/test/apps")
        values = {
            "manual_app": {
                "filename": "manual.py",
                "class_name": "ManualApp",
            }
        }

        with patch("hassette.config.core_config.auto_detect_app_manifests") as mock_auto_detect:
            result = validate_apps(values, app_dir, auto_detect=False)

            # Should not call auto_detect_app_manifests
            mock_auto_detect.assert_not_called()

            # Should only have the manual app
            assert len(result) == 1, f"Expected 1 app, got {len(result)}"
            assert "manual_app" in result, "Expected to find 'manual_app' in detected apps"


class TestAutoDetectIntegration:
    """Integration tests for auto-detect functionality with HassetteConfig."""

    def test_hassette_config_auto_detect_enabled_by_default(self, tmp_path: Path):
        """Test that auto_detect_apps is enabled by default in HassetteConfig."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "test_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class TestApp(App[AppConfig]): ...
        """)
        )

        # Create config with the temp app directory
        config = HassetteConfig(
            token="test-token",
            app_dir=app_dir,
            cli_parse_args=False,
        )

        # Should auto-detect the app
        assert "test_app.TestApp" in config.apps, "Expected to find 'test_app.TestApp' in detected apps"
        manifest = config.apps["test_app.TestApp"]
        assert manifest.filename == "test_app.py", f"Expected filename to be 'test_app.py', got {manifest.filename}"
        assert manifest.class_name == "TestApp", f"Expected class_name to be 'TestApp', got {manifest.class_name}"
        assert manifest.enabled is True, f"Expected enabled to be True, got {manifest.enabled}"

    def test_hassette_config_auto_detect_can_be_disabled(self, tmp_path: Path):
        """Test that auto_detect_apps can be disabled in HassetteConfig."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "test_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class TestApp(App[AppConfig]): ...
        """)
        )

        # Create config with auto-detect disabled
        config = HassetteConfig(
            token="test-token",
            app_dir=app_dir,
            auto_detect_apps=False,
            cli_parse_args=False,
        )

        # Should not auto-detect any apps
        assert len(config.apps) == 0, f"Expected 0 apps, got {len(config.apps)}"

    @pytest.mark.parametrize("ext", [".py", ""])
    def test_defined_filename_without_extension_is_handled(self, tmp_path: Path, ext: str):
        """If we define something in hassette.toml but forget the .py extension, we shouldn't load it twice.

        We handle the missing .py in the AppManifest, but we need to make sure that the auto-detect
        logic also handles this case correctly.

        """
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "priority_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class MyConfig(AppConfig):
                custom: str = "auto-app"

            class AutoDetectedApp(App[AppConfig]): ...
        """)
        )

        # Create config with manual app configuration that conflicts
        config = HassetteConfig(
            token="test-token",
            app_dir=app_dir,
            apps={
                "AutoDetectedApp": {
                    "filename": f"priority_app{ext}",
                    "class_name": "AutoDetectedApp",
                    "enabled": True,  # Different from auto-detect default
                    "config": {"custom": "value"},
                }
            },
            cli_parse_args=False,
        )

        # Should have the manual configuration, not auto-detected
        assert len(config.apps) == 1, f"Expected 1 app, got {len(config.apps)}"
        assert "AutoDetectedApp" in config.apps, "Expected to find 'priority_app.AutoDetectedApp' in detected apps"
        manifest = config.apps["AutoDetectedApp"]
        assert manifest.enabled is True, f"Expected enabled to be True, got {manifest.enabled}"
        assert manifest.app_config[0]["custom"] == "value", (
            f"Expected custom config to be 'value', got {manifest.app_config[0]['custom']}"
        )

    def test_hassette_config_manual_apps_take_precedence(self, tmp_path: Path):
        """Test that manually configured apps take precedence over auto-detected ones."""
        # Create a temporary app directory with an app
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        app_file = app_dir / "priority_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class AutoDetectedApp(App[AppConfig]): ...
        """)
        )

        # Create config with manual app configuration that conflicts
        config = HassetteConfig(
            token="test-token",
            app_dir=app_dir,
            apps={
                "priority_app.AutoDetectedApp": {
                    "filename": "priority_app.py",
                    "class_name": "AutoDetectedApp",
                    "enabled": False,  # Different from auto-detect default
                    "config": {"custom": "value"},
                }
            },
            cli_parse_args=False,
        )

        # Should have the manual configuration, not auto-detected
        assert len(config.apps) == 1, f"Expected 1 app, got {len(config.apps)}"
        assert "priority_app.AutoDetectedApp" in config.apps, (
            "Expected to find 'priority_app.AutoDetectedApp' in detected apps"
        )
        manifest = config.apps["priority_app.AutoDetectedApp"]
        assert manifest.enabled is False, f"Expected enabled to be False, got {manifest.enabled}"
        assert manifest.app_config[0]["custom"] == "value", (
            f"Expected custom config to be 'value', got {manifest.app_config[0]['custom']}"
        )

    def test_hassette_config_combines_manual_and_auto_detected(self, tmp_path: Path):
        """Test that HassetteConfig combines manual and auto-detected apps correctly."""
        # Create a temporary app directory with multiple apps
        app_dir = tmp_path / "apps"
        app_dir.mkdir()

        # Auto-detected app
        auto_file = app_dir / "auto_app.py"
        auto_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class AutoApp(App[AppConfig]): ...
        """)
        )

        # Manually configured app
        manual_file = app_dir / "manual_app.py"
        manual_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class ManualApp(App[AppConfig]): ...
        """)
        )

        # Create config with one manual app
        config = HassetteConfig(
            token="test-token",
            app_dir=app_dir,
            apps={"manual_app": {"filename": "manual_app.py", "class_name": "ManualApp", "config": {"manual": True}}},
            cli_parse_args=False,
        )

        # Should have both manual and auto-detected apps
        assert len(config.apps) == 2, f"Expected 2 apps, got {len(config.apps)}"
        assert "manual_app" in config.apps, "Expected to find 'manual_app' in detected apps"
        assert "auto_app.AutoApp" in config.apps, "Expected to find 'auto_app.AutoApp' in detected apps"

        # Manual app should preserve config
        manual_manifest = config.apps["manual_app"]
        assert manual_manifest.app_config[0]["manual"] is True, (
            f"Expected manual config to be True, got {manual_manifest.app_config[0]['manual']}"
        )

        # Auto-detected app should have default config
        auto_manifest = config.apps["auto_app.AutoApp"]
        assert auto_manifest.enabled is True, f"Expected enabled to be True, got {auto_manifest.enabled}"
