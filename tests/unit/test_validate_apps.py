"""Tests for the validate_apps / set_validated_app_manifests behavior.

Split out of `test_autodetect_apps.py` (see design/specs/100-decompose-oversized-test-files).
Complements `test_autodetect_apps.py` (TestAutoDetectAppsCurrDir, TestAutoDetectApps) and
`test_autodetect_apps_integration.py` (TestAutoDetectIntegration).
"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.testing import make_test_config
from tests.support.helpers import write_app


class TestValidateApps:
    """Test the validate_apps function."""

    def make_config(
        self,
        tmp_path: Path,
        *,
        autodetect: bool = False,
        directory: Path | None = None,
        apps: dict[str, Any] | None = None,
    ) -> HassetteConfig:
        apps_cfg: dict[str, Any] = {"autodetect": autodetect}
        if directory is not None:
            apps_cfg["directory"] = directory
        if apps is not None:
            apps_cfg["apps"] = apps
        return make_test_config(data_dir=tmp_path, apps=apps_cfg)

    def test_validate_apps_sets_app_dir(self, tmp_path: Path) -> None:
        """Test that validate_apps sets app_dir for apps that don't have it."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)
        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={"my_app": {"filename": "my_app.py", "class_name": "MyApp"}},
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        results = config.apps.manifests

        assert results["my_app"].app_dir == app_dir, (
            f"Expected app_dir to be {app_dir}, got {results['my_app'].app_dir}"
        )
        assert results["my_app"].app_key == "my_app", (
            f"Expected app_key to be 'my_app', got {results['my_app'].app_key}"
        )

    def test_validate_apps_preserves_existing_app_dir(self, tmp_path: Path) -> None:
        """Test that validate_apps preserves existing app_dir values."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)
        custom_dir = Path("/custom/location")

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={"my_app": {"filename": "my_app.py", "class_name": "MyApp", "app_dir": custom_dir}},
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        results = config.apps.manifests

        assert results["my_app"].app_dir == custom_dir, (
            f"Expected app_dir to be {custom_dir}, got {results['my_app'].app_dir}"
        )

    def test_validate_apps_removes_invalid_apps(self, tmp_path: Path) -> None:
        """Test that validate_apps removes apps missing required keys."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
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
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        result = config.apps.manifests

        # Only valid_app should remain - this is the important functional test
        assert len(result) == 1, f"Expected 1 valid app, got {len(result)}"
        assert "valid_app" in result, "Expected to find 'valid_app' in detected apps"
        assert "missing_filename" not in result, "Did not expect to find 'missing_filename' in detected apps"
        assert "missing_class_name" not in result, "Did not expect to find 'missing_class_name' in detected apps"
        assert "missing_both" not in result, "Did not expect to find 'missing_both' in detected apps"

        # The valid app should have the app_dir and app_key set
        assert result["valid_app"].app_dir == app_dir, (
            f"Expected app_dir to be {app_dir}, got {result['valid_app'].app_dir}"
        )
        assert result["valid_app"].app_key == "valid_app", (
            f"Expected app_key to be 'valid_app', got {result['valid_app'].app_key}"
        )

    def test_validate_apps_merges_autodetected_and_manual_apps(self, tmp_path: Path) -> None:
        """Real discovery runs when autodetect=True and merges with manually configured apps."""
        # `app_dir.name` is load-bearing, not scaffolding: autodetect_apps() passes it as the
        # package name, so a discovered app's key is "{app_dir.name}.{module_stem}.{class_name}"
        # — the literals asserted below change if this directory is renamed.
        app_dir = tmp_path / "test_apps"
        write_app(
            app_dir,
            "validate_auto_app.py",
            """
            from hassette import App, AppConfig

            class ValidateAutoApp(App[AppConfig]): ...
            """,
        )
        write_app(
            app_dir,
            "validate_manual_app.py",
            """
            from hassette import App, AppConfig

            class ValidateManualApp(App[AppConfig]): ...
            """,
        )

        config = self.make_config(
            tmp_path,
            autodetect=True,
            directory=app_dir,
            apps={
                "manual_app": {
                    "filename": "validate_manual_app.py",
                    "class_name": "ValidateManualApp",
                }
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        result = config.apps.manifests

        autodetected_key = "test_apps.validate_auto_app.ValidateAutoApp"
        assert sorted(result) == sorted(["manual_app", autodetected_key]), (
            f"Expected the manual app plus the auto-detected one, got {sorted(result)}"
        )

        # Discovery ran against the configured app directory.
        auto_manifest = result[autodetected_key]
        assert auto_manifest.app_dir == app_dir, f"Expected app_dir to be {app_dir}, got {auto_manifest.app_dir}"
        assert auto_manifest.filename == "validate_auto_app.py", (
            f"Expected filename to be 'validate_auto_app.py', got {auto_manifest.filename}"
        )

        # The manually configured file is handed to discovery as a known path, so it is not
        # detected a second time under its derived key.
        assert "test_apps.validate_manual_app.ValidateManualApp" not in result, (
            f"Expected the manually configured file to be skipped by discovery, got {sorted(result)}"
        )

    def test_validate_apps_skips_conflicting_autodetected(self, tmp_path: Path) -> None:
        """Auto-detected apps whose key is already claimed by a manual app are dropped.

        The manual entry deliberately points at a *different* file than the one discovery finds:
        a manually configured file is excluded from discovery via known_paths, so pointing both
        at the same file would never reach the key-conflict branch.
        """
        # Same "{app_dir.name}.{module_stem}.{class_name}" key format as the test above.
        app_dir = tmp_path / "test_apps"
        write_app(
            app_dir,
            "validate_conflict_app.py",
            """
            from hassette import App, AppConfig

            class ValidateConflictApp(App[AppConfig]): ...
            """,
        )
        write_app(
            app_dir,
            "validate_override_app.py",
            """
            from hassette import App, AppConfig

            class ValidateOverrideApp(App[AppConfig]): ...
            """,
        )

        conflicting_key = "test_apps.validate_conflict_app.ValidateConflictApp"
        config = self.make_config(
            tmp_path,
            autodetect=True,
            directory=app_dir,
            apps={
                conflicting_key: {
                    "filename": "validate_override_app.py",
                    "class_name": "ValidateOverrideApp",
                }
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        result = config.apps.manifests

        # Only the manual app survives — the auto-detected app that resolved to the same key
        # is skipped rather than overwriting it.
        assert sorted(result) == [conflicting_key], f"Expected only {conflicting_key!r}, got {sorted(result)}"
        manifest = result[conflicting_key]
        assert manifest.filename == "validate_override_app.py", (
            f"Expected filename to be 'validate_override_app.py', got {manifest.filename}"
        )
        assert manifest.class_name == "ValidateOverrideApp", (
            f"Expected class_name to be 'ValidateOverrideApp', got {manifest.class_name}"
        )

    def test_validate_apps_skips_autodetect_when_disabled(self, tmp_path: Path) -> None:
        """Test that validate_apps skips auto-detection when autodetect=False."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "manual_app": {
                    "filename": "manual.py",
                    "class_name": "ManualApp",
                }
            },
        )

        with patch("hassette.config.config.autodetect_apps") as mock_autodetect:
            with context.use_hassette_config(config):
                config.set_validated_app_manifests()
            result = config.apps.manifests

            # Should not call autodetect_apps since autodetect=False
            mock_autodetect.assert_not_called()

            # Should only have the manual app
            assert len(result) == 1, f"Expected 1 app, got {len(result)}"
            assert "manual_app" in result, "Expected to find 'manual_app' in detected apps"

    def test_validate_apps_warns_on_cache_key_collision(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Two apps with different app_key but the same explicit cache_key log a WARNING."""
        # Some other test in this session may have left the "hassette" logger's propagate flag
        # set to False (e.g. via enable_basic_logging()); caplog relies on propagation to the
        # root logger, so restore it here. See src/hassette/testing/_harness.py:337-340 for
        # the same workaround applied elsewhere.
        logging.getLogger("hassette").propagate = True
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "app_one": {
                    "filename": "app_one.py",
                    "class_name": "AppOne",
                    "cache_key": "shared-key",
                },
                "app_two": {
                    "filename": "app_two.py",
                    "class_name": "AppTwo",
                    "cache_key": "shared-key",
                },
            },
        )

        with context.use_hassette_config(config), caplog.at_level("WARNING", logger="hassette.config.config"):
            config.set_validated_app_manifests()

        assert any("shared-key" in record.message for record in caplog.records), (
            f"Expected a WARNING mentioning the colliding cache_key, got: {[r.message for r in caplog.records]}"
        )

    def test_validate_apps_no_warning_when_cache_keys_unique(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Apps with distinct (or default) cache_keys produce no collision warning."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "app_one": {"filename": "app_one.py", "class_name": "AppOne"},
                "app_two": {"filename": "app_two.py", "class_name": "AppTwo"},
            },
        )

        with context.use_hassette_config(config), caplog.at_level("WARNING", logger="hassette.config.config"):
            config.set_validated_app_manifests()

        assert not any("cache_key" in record.message for record in caplog.records), (
            f"Expected no cache_key collision warning, got: {[r.message for r in caplog.records]}"
        )

    def test_validate_apps_warns_on_multi_instance_default_key_collision(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A multi-instance app's default `{app_key}/{idx}` key can collide with another
        app's explicit cache_key — the collision check must expand multi-instance app_config
        lists to each instance's resolved key, not just check the manifest as a whole.
        """
        # See comment in test_validate_apps_warns_on_cache_key_collision above.
        logging.getLogger("hassette").propagate = True
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "weather": {
                    "filename": "weather.py",
                    "class_name": "Weather",
                    "config": [{"city": "nyc"}, {"city": "sf"}],
                },
                "other_app": {
                    "filename": "other_app.py",
                    "class_name": "OtherApp",
                    "cache_key": "weather/1",
                },
            },
        )

        with context.use_hassette_config(config), caplog.at_level("WARNING", logger="hassette.config.config"):
            config.set_validated_app_manifests()

        assert any("weather/1" in record.message for record in caplog.records), (
            f"Expected a WARNING mentioning the colliding cache_key 'weather/1', "
            f"got: {[r.message for r in caplog.records]}"
        )
