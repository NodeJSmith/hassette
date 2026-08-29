"""Tests for auto-detect apps functionality.

Complements test_validate_apps.py (TestValidateApps) and test_autodetect_apps_integration.py
(TestAutoDetectIntegration), which were split out of this file.
"""

from pathlib import Path

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.config.defaults import AUTODETECT_EXCLUDE_DIRS_DEFAULT
from hassette.test_utils import write_app
from hassette.types.types import AppDict
from hassette.utils.app_utils import autodetect_apps


def detect(app_dir: Path, known_paths: set[Path] | None = None) -> dict[str, AppDict]:
    """Run autodetect_apps over `app_dir` with the production exclude list."""
    return autodetect_apps(app_dir, known_paths or set(), set(AUTODETECT_EXCLUDE_DIRS_DEFAULT))


def assert_detected(result: dict[str, AppDict], *app_keys: str) -> None:
    """Assert the detected app keys are exactly `app_keys` — nothing missing, nothing extra."""
    assert sorted(result) == sorted(app_keys), f"Expected {sorted(app_keys)}, got {sorted(result)}"


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
        write_app(
            tmp_path,
            "current_dir_app.py",
            """
            from hassette import App, AppConfig

            class CurrentDirApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(tmp_path), f"{tmp_path.name}.current_dir_app.CurrentDirApp")

    def test_autodetect_ignores_venv_directory(self, tmp_path: Path):
        """Test that auto-detection ignores .venv directory."""
        write_app(
            tmp_path / ".venv",
            "venv_app.py",
            """
            from hassette import App, AppConfig

            class VenvApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(tmp_path))

    def test_autodetect_ignores_hidden_directories(self, tmp_path: Path):
        """Test that auto-detection ignores hidden directories."""
        write_app(
            tmp_path / ".hidden",
            "hidden_app.py",
            """
            from hassette import App, AppConfig

            class HiddenApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(tmp_path))


class TestAutoDetectApps:
    """Test the autodetect_apps function."""

    @pytest.fixture(autouse=True)
    def setup(self, test_config: HassetteConfig):
        with context.use_hassette_config(test_config):
            yield

    def test_autodetect_simple_app(self, tmp_path: Path):
        """Test auto-detection of a simple app in the root directory."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "simple_app.py",
            """
            from hassette import App, AppConfig

            class SimpleAppConfig(AppConfig):
                message: str = "Hello"

            class SimpleApp(App[SimpleAppConfig]): ...
            """,
        )

        result = detect(app_dir)
        assert_detected(result, "apps.simple_app.SimpleApp")

        app_dict = result["apps.simple_app.SimpleApp"]
        assert app_dict["filename"] == "simple_app.py"
        assert app_dict["class_name"] == "SimpleApp"
        assert app_dict["app_dir"] == app_dir
        assert app_dict["app_key"] == "apps.simple_app.SimpleApp"
        assert app_dict["enabled"] is True

    def test_autodetect_sync_app(self, tmp_path: Path):
        """Test auto-detection of a sync app."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "sync_app.py",
            """
            from hassette import AppSync, AppConfig

            class SyncAppConfig(AppConfig):
                interval: int = 60

            class MySyncApp(AppSync[SyncAppConfig]): ...
            """,
        )

        result = detect(app_dir)
        assert_detected(result, "apps.sync_app.MySyncApp")

        app_dict = result["apps.sync_app.MySyncApp"]
        assert app_dict["filename"] == "sync_app.py"
        assert app_dict["class_name"] == "MySyncApp"

    def test_autodetect_multiple_apps_in_file(self, tmp_path: Path):
        """Test auto-detection when multiple app classes exist in one file."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "multi_apps.py",
            """
            from hassette import App, AppSync, AppConfig

            class SharedConfig(AppConfig):
                name: str = "test"

            class FirstApp(App[SharedConfig]): ...

            class SecondApp(AppSync[SharedConfig]): ...
            """,
        )

        result = detect(app_dir)
        assert_detected(result, "apps.multi_apps.FirstApp", "apps.multi_apps.SecondApp")

        assert result["apps.multi_apps.FirstApp"]["class_name"] == "FirstApp"
        assert result["apps.multi_apps.SecondApp"]["class_name"] == "SecondApp"

    def test_autodetect_nested_directory(self, tmp_path: Path):
        """Test auto-detection of apps in nested directories."""
        app_dir = tmp_path / "apps"
        app_dir.mkdir()
        write_app(
            app_dir / "notifications",
            "email_notifier.py",
            """
            from hassette import App, AppConfig

            class EmailConfig(AppConfig):
                smtp_server: str = "localhost"

            class EmailNotifier(App[EmailConfig]): ...
            """,
        )

        result = detect(app_dir)
        assert_detected(result, "apps.notifications.email_notifier.EmailNotifier")

        app_dict = result["apps.notifications.email_notifier.EmailNotifier"]
        assert app_dict["filename"] == "email_notifier.py"
        assert app_dict["class_name"] == "EmailNotifier"
        assert app_dict["app_key"] == "apps.notifications.email_notifier.EmailNotifier"

    def test_autodetect_skips_known_paths(self, tmp_path: Path):
        """Test that auto-detection skips already configured apps."""
        app_dir = tmp_path / "apps"
        app_file = write_app(
            app_dir,
            "configured_app.py",
            """
            from hassette import App, AppConfig

            class ConfiguredApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(app_dir, known_paths={app_file.resolve()}))

    def test_autodetect_ignores_base_classes(self, tmp_path: Path):
        """Test that auto-detection ignores the base App and AppSync classes."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "base_classes.py",
            """
            from hassette import App, AppSync, AppConfig

            # These should not be detected
            App = App
            AppSync = AppSync

            class RealApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(app_dir), "apps.base_classes.RealApp")

    def test_autodetect_ignores_imported_classes(self, tmp_path: Path):
        """Test that auto-detection ignores classes imported from other modules."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "my_module.py",
            """
            from hassette import App, AppConfig

            class ModuleApp(App[AppConfig]): ...
            """,
        )
        write_app(
            app_dir,
            "importer.py",
            """
            from my_module import ModuleApp
            from hassette import App, AppConfig

            class LocalApp(App[AppConfig]): ...
            """,
        )

        # Each app is detected in its own module; ModuleApp must NOT appear under importer.py
        assert_detected(detect(app_dir), "apps.my_module.ModuleApp", "apps.importer.LocalApp")

    def test_autodetect_handles_import_errors(self, tmp_path: Path):
        """Test that auto-detection gracefully handles files with import errors."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "broken_app.py",
            """
            from nonexistent_module import SomethingThatDoesntExist
            from hassette import App, AppConfig

            class BrokenApp(App[AppConfig]): ...
            """,
        )
        write_app(
            app_dir,
            "good_app.py",
            """
            from hassette import App, AppConfig

            class GoodApp(App[AppConfig]): ...
            """,
        )

        # The broken module is skipped rather than aborting the whole scan
        result = detect(app_dir)
        assert_detected(result, "apps.good_app.GoodApp")

        good_app_dict = result["apps.good_app.GoodApp"]
        assert good_app_dict["filename"] == "good_app.py"
        assert good_app_dict["class_name"] == "GoodApp"

    def test_autodetect_ignores_non_app_classes(self, tmp_path: Path):
        """Test that auto-detection ignores classes that don't inherit from App/AppSync."""
        app_dir = tmp_path / "apps"
        write_app(
            app_dir,
            "mixed_classes.py",
            """
            from hassette import App, AppConfig

            class RegularClass:
                pass

            class MyService:
                def do_something(self):
                    pass

            class ActualApp(App[AppConfig]): ...
            """,
        )

        assert_detected(detect(app_dir), "apps.mixed_classes.ActualApp")
