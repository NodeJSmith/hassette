"""Tests for the validate_apps / set_validated_app_manifests behavior."""

from pathlib import Path
from typing import Any

import pytest

from hassette import context
from hassette.config.config import HassetteConfig
from hassette.core.app_registry import AppRegistry
from hassette.exceptions import ConfigError
from hassette.testing import make_test_config
from hassette.web.mappers import app_summary_from


@pytest.fixture
def app_dir(tmp_path: Path) -> Path:
    """Return an existing, empty app directory under `tmp_path`."""
    path = tmp_path / "test_apps"
    path.mkdir(parents=True, exist_ok=True)
    return path


def make_two_apps(
    *,
    cache_key_one: str | None = None,
    cache_key_two: str | None = None,
    shared_one: bool = False,
    shared_two: bool = False,
) -> dict[str, Any]:
    """Build an `apps` config with two single-instance apps, `app_one` and `app_two`.

    `cache_key`/`cache_shared` are only set on an app when given, so omitted values exercise the defaults.
    """
    apps: dict[str, Any] = {}
    for app_key, class_name, cache_key, cache_shared in (
        ("app_one", "AppOne", cache_key_one, shared_one),
        ("app_two", "AppTwo", cache_key_two, shared_two),
    ):
        app: dict[str, Any] = {
            "filename": f"{app_key}.py",
            "class_name": class_name,
            "config": {"instance_name": app_key},
        }
        if cache_key is not None:
            app["cache_key"] = cache_key
        if cache_shared:
            app["cache_shared"] = True
        apps[app_key] = app
    return apps


class TestValidateApps:
    """Test the validate_apps function."""

    def make_config(
        self,
        tmp_path: Path,
        *,
        directory: Path | None = None,
        apps: dict[str, Any] | None = None,
    ) -> HassetteConfig:
        apps_cfg: dict[str, Any] = {}
        if directory is not None:
            apps_cfg["directory"] = directory
        if apps is not None:
            apps_cfg["apps"] = apps
        return make_test_config(data_dir=tmp_path, apps=apps_cfg)

    def test_validate_apps_sets_app_dir(self, tmp_path: Path, app_dir: Path) -> None:
        """Test that validate_apps sets app_dir for apps that don't have it."""
        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={"my_app": {"filename": "my_app.py", "class_name": "MyApp", "config": {"instance_name": "my_app"}}},
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

    def test_validate_apps_preserves_existing_app_dir(self, tmp_path: Path, app_dir: Path) -> None:
        """Test that validate_apps preserves existing app_dir values."""
        custom_dir = Path("/custom/location")

        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "my_app": {
                    "filename": "my_app.py",
                    "class_name": "MyApp",
                    "app_dir": custom_dir,
                    "config": {"instance_name": "my_app"},
                }
            },
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        results = config.apps.manifests

        assert results["my_app"].app_dir == custom_dir, (
            f"Expected app_dir to be {custom_dir}, got {results['my_app'].app_dir}"
        )

    def test_validate_apps_removes_invalid_apps(self, tmp_path: Path, app_dir: Path) -> None:
        """Test that validate_apps removes apps missing required keys."""
        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={
                "valid_app": {
                    "filename": "valid.py",
                    "class_name": "ValidApp",
                    "config": {"instance_name": "valid_app"},
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

    @pytest.mark.parametrize(
        ("app_key", "reason"),
        [
            ("../../elsewhere", "path separators"),
            ("bar/../foo", "path separators"),
            ("nested/key", "path separators"),
            ("/abs/path", "path separators"),
            ("win\\style", "path separators"),
            ("..", "parent-directory traversal"),
            ("C:", "relative path"),
            ("", "subdirectory"),
            (".", "subdirectory"),
        ],
    )
    def test_validate_apps_rejects_path_unsafe_app_key(
        self, tmp_path: Path, app_dir: Path, app_key: str, reason: str
    ) -> None:
        """App keys that would escape or alias a cache directory are rejected, naming the key and its source."""
        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={app_key: {"filename": "my_app.py", "class_name": "MyApp", "config": {"instance_name": "my_app"}}},
        )

        with context.use_hassette_config(config), pytest.raises(ValueError, match=reason) as exc_info:
            config.set_validated_app_manifests()

        message = str(exc_info.value)
        assert repr(app_key) in message, f"Expected the error to name the key {app_key!r}, got: {message}"
        assert str(app_dir / "my_app.py") in message, f"Expected the error to name the source file, got: {message}"

    @pytest.mark.parametrize("app_key", ["my_app", "my-app", "test_apps.my_module.MyApp", "a..b"])
    def test_validate_apps_accepts_ordinary_app_keys(self, tmp_path: Path, app_dir: Path, app_key: str) -> None:
        """Plain and dotted app keys pass validation."""
        config = self.make_config(
            tmp_path,
            directory=app_dir,
            apps={app_key: {"filename": "my_app.py", "class_name": "MyApp", "config": {"instance_name": "my_app"}}},
        )

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()

        assert app_key in config.apps.manifests, f"Expected {app_key!r} in manifests, got {list(config.apps.manifests)}"

    def warning_messages(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture, apps: dict[str, Any]
    ) -> list[str]:
        """Validate `apps` and return the messages of every WARNING the config module logged."""
        config = self.make_config(tmp_path, directory=app_dir, apps=apps)
        with context.use_hassette_config(config), caplog.at_level("WARNING", logger="hassette.config.config"):
            config.set_validated_app_manifests()
        return [record.message for record in caplog.records]

    def test_validate_apps_warns_on_cache_key_collision(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Two apps with different app_key but the same explicit cache_key log a WARNING."""
        messages = self.warning_messages(
            tmp_path, app_dir, caplog, make_two_apps(cache_key_one="shared-key", cache_key_two="shared-key")
        )

        assert any("shared-key" in message for message in messages), (
            f"Expected a WARNING mentioning the colliding cache_key, got: {messages}"
        )

    def test_validate_apps_no_warning_when_cache_keys_unique(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Apps with distinct (or default) cache_keys produce no collision warning."""
        messages = self.warning_messages(tmp_path, app_dir, caplog, make_two_apps())

        assert not any("cache_key" in message for message in messages), (
            f"Expected no cache_key collision warning, got: {messages}"
        )

    def test_validate_apps_warns_on_multi_instance_default_key_collision(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A multi-instance app's default `{app_key}/{idx}` key can collide with another
        app's explicit cache_key — the collision check must expand multi-instance app_config
        lists to each instance's resolved key, not just check the manifest as a whole.
        """
        apps = {
            "weather": {
                "filename": "weather.py",
                "class_name": "Weather",
                "config": [
                    {"city": "nyc", "instance_name": "weather_nyc"},
                    {"city": "sf", "instance_name": "weather_sf"},
                ],
            },
            "other_app": {
                "filename": "other_app.py",
                "class_name": "OtherApp",
                "config": {"instance_name": "other_app"},
                "cache_key": "weather/1",
            },
        }
        messages = self.warning_messages(tmp_path, app_dir, caplog, apps)

        assert any("weather/1" in message for message in messages), (
            f"Expected a WARNING mentioning the colliding cache_key 'weather/1', got: {messages}"
        )

    def test_validate_apps_no_warning_when_all_sharers_opt_in(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Apps that share a cache_key and all set cache_shared = true produce no collision warning."""
        apps = make_two_apps(cache_key_one="shared-key", cache_key_two="shared-key", shared_one=True, shared_two=True)
        messages = self.warning_messages(tmp_path, app_dir, caplog, apps)

        assert not any("shared-key" in message for message in messages), (
            f"Expected no cache_key collision warning, got: {messages}"
        )

    def test_cache_shared_reaches_manifest(self, tmp_path: Path, app_dir: Path) -> None:
        """`cache_shared = true` in config is carried onto the validated manifest."""
        apps = make_two_apps(cache_key_one="shared-key", cache_key_two="shared-key", shared_one=True, shared_two=True)
        config = self.make_config(tmp_path, directory=app_dir, apps=apps)

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()

        assert all(manifest.cache_shared for manifest in config.apps.manifests.values())

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            pytest.param({"display_name": "Front door: cast cameras"}, "Front door: cast cameras", id="configured"),
            pytest.param({}, "my_app", id="defaults_to_app_key"),
        ],
    )
    def test_display_name_reaches_manifest_and_summary(
        self, tmp_path: Path, app_dir: Path, extra: dict[str, str], expected: str
    ) -> None:
        """`display_name` in config is carried onto the manifest and the API summary; unset, it is the app key."""
        apps = {
            "my_app": {"filename": "my_app.py", "class_name": "MyApp", "config": {"instance_name": "my_app"}, **extra}
        }
        config = self.make_config(tmp_path, directory=app_dir, apps=apps)

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        manifest = config.apps.manifests["my_app"]
        summary = app_summary_from(AppRegistry().build_manifest_info("my_app", manifest))

        assert manifest.display_name == expected
        assert summary.display_name == expected

    @pytest.mark.parametrize(
        ("extra", "expected"),
        [
            pytest.param({"description": "  Turns on the porch light  "}, "Turns on the porch light", id="configured"),
            pytest.param({}, None, id="unset"),
        ],
    )
    def test_description_reaches_manifest_and_summary(
        self, tmp_path: Path, app_dir: Path, extra: dict[str, str], expected: str | None
    ) -> None:
        """`description` in config survives cleaning onto the manifest and the API summary; unset, it is None."""
        apps = {
            "my_app": {"filename": "my_app.py", "class_name": "MyApp", "config": {"instance_name": "my_app"}, **extra}
        }
        config = self.make_config(tmp_path, directory=app_dir, apps=apps)

        with context.use_hassette_config(config):
            config.set_validated_app_manifests()
        manifest = config.apps.manifests["my_app"]
        summary = app_summary_from(AppRegistry().build_manifest_info("my_app", manifest))

        assert manifest.description == expected
        assert summary.description == expected

    def test_multiline_description_in_config_is_rejected(self, tmp_path: Path, app_dir: Path) -> None:
        """A configured description with a line break fails validation instead of being silently dropped."""
        apps = {
            "my_app": {
                "filename": "my_app.py",
                "class_name": "MyApp",
                "config": {"instance_name": "my_app"},
                "description": "line one\nline two",
            }
        }
        config = self.make_config(tmp_path, directory=app_dir, apps=apps)

        with context.use_hassette_config(config), pytest.raises(ConfigError, match="single line"):
            config.set_validated_app_manifests()

    def test_validate_apps_warns_on_partial_cache_shared_opt_in(
        self, tmp_path: Path, app_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If only some sharers opt in, the warning still fires and names the apps missing the flag."""
        apps = make_two_apps(cache_key_one="shared-key", cache_key_two="shared-key", shared_one=True)
        messages = self.warning_messages(tmp_path, app_dir, caplog, apps)

        warnings = [message for message in messages if "shared-key" in message]
        assert len(warnings) == 1, f"Expected one collision WARNING, got: {messages}"
        assert "without `cache_shared = true`: ['app_two']" in warnings[0]
