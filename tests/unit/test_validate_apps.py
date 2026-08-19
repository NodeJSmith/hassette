"""Tests for the validate_apps / set_validated_app_manifests behavior.

Split out of `test_autodetect_apps.py` (see design/specs/100-decompose-oversized-test-files).
Complements `test_autodetect_apps.py` (TestAutoDetectAppsCurrDir, TestAutoDetectApps) and
`test_autodetect_apps_integration.py` (TestAutoDetectIntegration).
"""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.test_utils.config import make_test_config


class TestValidateApps:
    """Test the validate_apps function."""

    def make_config(
        self,
        tmp_path: Path,
        *,
        autodetect: bool = False,
        directory: Path | None = None,
        apps: dict | None = None,
    ) -> HassetteConfig:
        apps_cfg: dict = {"autodetect": autodetect}
        if directory is not None:
            apps_cfg["directory"] = directory
        if apps is not None:
            apps_cfg["apps"] = apps
        return make_test_config(data_dir=tmp_path, apps=apps_cfg)

    def test_validate_apps_sets_app_dir(self, tmp_path: Path):
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

    def test_validate_apps_preserves_existing_app_dir(self, tmp_path: Path):
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

    def test_validate_apps_removes_invalid_apps(self, tmp_path: Path):
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

    @patch("hassette.config.config.autodetect_apps")
    def test_validate_apps_calls_autodetect(self, mock_autodetect, tmp_path: Path):
        """Test that validate_apps calls autodetect_app_manifests when autodetect=True."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Mock the auto-detection to return a detected app
        mock_app_dict = {
            "filename": "auto.py",
            "class_name": "AutoApp",
            "app_dir": app_dir,
            "app_key": "auto.AutoApp",
            "enabled": True,
            "full_path": app_dir / "auto.py",
        }
        mock_autodetect.return_value = {"auto.AutoApp": mock_app_dict}

        config = self.make_config(
            tmp_path,
            autodetect=True,
            directory=app_dir,
            apps={
                "manual_app": {
                    "filename": "manual.py",
                    "class_name": "ManualApp",
                }
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should have both manual and auto-detected apps
        assert len(result) == 2, f"Expected 2 apps, got {len(result)}"
        assert "manual_app" in result, "Expected to find 'manual_app' in detected apps"
        assert "auto.AutoApp" in result, "Expected to find 'auto.AutoApp' in detected apps"

        # Check that autodetect_app_manifests was called with correct parameters
        mock_autodetect.assert_called_once()
        args, _ = mock_autodetect.call_args
        assert args[0] == app_dir, f"Expected app_dir to be {app_dir}, got {args[0]}"
        # Should include the path of the manual app in known_paths
        known_paths = args[1]
        expected_path = (app_dir / "manual.py").resolve()
        assert expected_path in known_paths, f"Expected known_paths to include {expected_path}, got {known_paths}"

    @patch("hassette.config.config.autodetect_apps")
    def test_validate_apps_skips_conflicting_autodetected(self, mock_autodetect, tmp_path: Path):
        """Test that validate_apps skips auto-detected apps that conflict with manual ones."""
        app_dir = tmp_path / "test_apps"
        app_dir.mkdir(parents=True, exist_ok=True)

        # Mock auto-detection to return an app with the same key
        mock_app_dict = {
            "filename": "my_app.py",
            "class_name": "MyApp",
            "app_dir": app_dir,
            "app_key": "my_app",
            "enabled": True,
        }
        mock_autodetect.return_value = {"my_app": mock_app_dict}

        config = self.make_config(
            tmp_path,
            autodetect=True,
            directory=app_dir,
            apps={
                "my_app": {
                    "filename": "my_app.py",
                    "class_name": "MyApp",
                }
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        result = config.apps.manifests

        # Should only have the manual app, not the auto-detected one
        assert len(result) == 1, f"Expected 1 app, got {len(result)}"
        assert "my_app" in result, "Expected to find 'my_app' in detected apps"
        # Should be the original manual config, not the auto-detected one
        assert result["my_app"].filename == "my_app.py", (
            f"Expected filename to be 'my_app.py', got {result['my_app'].filename}"
        )
        assert result["my_app"].class_name == "MyApp", (
            f"Expected class_name to be 'MyApp', got {result['my_app'].class_name}"
        )

        # The behavior is that auto-detected apps with conflicting keys are simply not added
        # Let's verify that autodetect_app_manifests was called and the result is correct
        mock_autodetect.assert_called_once()
        # The important thing is that the result only contains the manual app

    def test_validate_apps_skips_autodetect_when_disabled(self, tmp_path: Path):
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
        # root logger, so restore it here. See src/hassette/test_utils/harness.py:337-340 for
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
