"""Tests for auto-detect apps functionality."""

from pathlib import Path
from textwrap import dedent

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.utils.app_utils import autodetect_apps


class TestAutoDetectAppsCurrDir:
    """Test the autodetect_apps function with current directory.

    This ensures we do not attempt to, for example, read every file in .venv
    or similar directories. It also checks that we handle importing files when we do not have a
    standard package directory structure.
    """

    @pytest.fixture(autouse=True)
    def setup(self, test_config: HassetteConfig):
        with context.use_hassette_config(test_config):
            yield

    def test_autodetect_in_current_directory(self, tmp_path: Path):
        """Test auto-detection of apps in the current directory."""
        # Create a simple app file in the temp directory
        app_file = tmp_path / "current_dir_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class CurrentDirApp(App[AppConfig]): ...
        """)
        )
        expected = f"{tmp_path.name}.current_dir_app.CurrentDirApp"

        known_paths = set()
        result = autodetect_apps(tmp_path, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert expected in result, f"Expected to find '{expected}' in detected apps"

    def test_autodetect_ignores_venv_directory(self, tmp_path: Path):
        """Test that auto-detection ignores .venv directory."""
        # Create a .venv directory with an app file
        venv_dir = tmp_path / ".venv"
        venv_dir.mkdir()

        app_file = venv_dir / "venv_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class VenvApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = autodetect_apps(tmp_path, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))
        assert len(result) == 0, f"Expected 0 apps, got {len(result)}"
        assert "venv_app.VenvApp" not in result, "Did not expect to find 'venv_app.VenvApp' in detected apps"

    def test_autodetect_ignores_hidden_directories(self, tmp_path: Path):
        """Test that auto-detection ignores hidden directories."""
        # Create a hidden directory with an app file
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()

        app_file = hidden_dir / "hidden_app.py"
        app_file.write_text(
            dedent("""
            from hassette import App, AppConfig

            class HiddenApp(App[AppConfig]): ...
        """)
        )

        known_paths = set()
        result = autodetect_apps(tmp_path, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))
        assert len(result) == 0, f"Expected 0 apps, got {len(result)}"
        assert "hidden_app.HiddenApp" not in result, "Did not expect to find 'hidden_app.HiddenApp' in detected apps"


class TestAutoDetectApps:
    """Test the autodetect_apps function."""

    @pytest.fixture(autouse=True)
    def setup(self, test_config: HassetteConfig):
        with context.use_hassette_config(test_config):
            yield

    def test_autodetect_simple_app(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        assert len(result) == 1
        assert "apps.simple_app.SimpleApp" in result

        app_dict = result["apps.simple_app.SimpleApp"]
        assert app_dict["filename"] == "simple_app.py", f"Expected 'simple_app.py', got '{app_dict['filename']}'"
        assert app_dict["class_name"] == "SimpleApp", f"Expected 'SimpleApp', got '{app_dict['class_name']}'"
        assert app_dict["app_dir"] == app_dir, f"Expected '{app_dir}', got '{app_dict['app_dir']}'"
        assert app_dict["app_key"] == "apps.simple_app.SimpleApp", (
            f"Expected 'apps.simple_app.SimpleApp', got '{app_dict['app_key']}'"
        )
        assert app_dict["enabled"] is True, f"Expected 'True', got '{app_dict['enabled']}'"

    def test_autodetect_sync_app(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        assert len(result) == 1
        assert "apps.sync_app.MySyncApp" in result, "Expected to find 'apps.sync_app.MySyncApp' in detected apps"

        app_dict = result["apps.sync_app.MySyncApp"]
        assert app_dict["filename"] == "sync_app.py", f"Expected 'sync_app.py', got '{app_dict['filename']}'"
        assert app_dict["class_name"] == "MySyncApp", f"Expected 'MySyncApp', got '{app_dict['class_name']}'"

    def test_autodetect_multiple_apps_in_file(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "apps.multi_apps.FirstApp" in result, "Expected to find 'apps.multi_apps.FirstApp' in detected apps"
        assert "apps.multi_apps.SecondApp" in result, "Expected to find 'apps.multi_apps.SecondApp' in detected apps"

        first_app_dict = result["apps.multi_apps.FirstApp"]
        assert first_app_dict["class_name"] == "FirstApp", f"Expected 'FirstApp', got '{first_app_dict['class_name']}'"

        second_app_dict = result["apps.multi_apps.SecondApp"]
        assert second_app_dict["class_name"] == "SecondApp", (
            f"Expected 'SecondApp', got '{second_app_dict['class_name']}'"
        )

    def test_autodetect_nested_directory(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "apps.notifications.email_notifier.EmailNotifier" in result, (
            "Expected to find 'apps.notifications.email_notifier.EmailNotifier' in detected apps"
        )

        app_dict = result["apps.notifications.email_notifier.EmailNotifier"]
        assert app_dict["filename"] == "email_notifier.py", (
            f"Expected 'email_notifier.py', got '{app_dict['filename']}'"
        )
        assert app_dict["class_name"] == "EmailNotifier", f"Expected 'EmailNotifier', got '{app_dict['class_name']}'"
        assert app_dict["app_key"] == "apps.notifications.email_notifier.EmailNotifier", (
            f"Expected 'apps.notifications.email_notifier.EmailNotifier', got '{app_dict['app_key']}'"
        )

    def test_autodetect_skips_known_paths(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        assert len(result) == 0, "Expected no apps to be detected since the only app is in known_paths"

    def test_autodetect_ignores_base_classes(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        # Should only find RealApp, not App or AppSync
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "apps.base_classes.RealApp" in result, "Expected to find 'apps.base_classes.RealApp' in detected apps"

    def test_autodetect_ignores_imported_classes(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        # Should find both apps, but each in their own module
        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "apps.my_module.ModuleApp" in result, "Expected to find 'apps.my_module.ModuleApp' in detected apps"
        assert "apps.importer.LocalApp" in result, "Expected to find 'apps.importer.LocalApp' in detected apps"
        # ModuleApp should NOT be detected in importer.py
        assert "apps.importer.ModuleApp" not in result, (
            "Did not expect to find 'apps.importer.ModuleApp' in detected apps"
        )

    def test_autodetect_handles_import_errors(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        # Should only find the good app, not the broken one - this is the key functional test
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "apps.good_app.GoodApp" in result, "Expected to find 'apps.good_app.GoodApp' in detected apps"
        assert "apps.broken_app.BrokenApp" not in result, (
            "Did not expect to find 'apps.broken_app.BrokenApp' in detected apps"
        )

        # Verify the detected app has correct properties
        good_app_dict = result["apps.good_app.GoodApp"]
        assert good_app_dict["filename"] == "good_app.py", f"Expected 'good_app.py', got '{good_app_dict['filename']}'"
        assert good_app_dict["class_name"] == "GoodApp", f"Expected 'GoodApp', got '{good_app_dict['class_name']}'"

    def test_autodetect_ignores_non_app_classes(self, tmp_path: Path):
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
        result = autodetect_apps(app_dir, known_paths, set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))

        # Should only find the actual app class
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "apps.mixed_classes.ActualApp" in result, (
            "Expected to find 'apps.mixed_classes.ActualApp' in detected apps"
        )
