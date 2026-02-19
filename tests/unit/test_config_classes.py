"""Tests for model_dump privacy behavior on AppManifest and HassetteConfig.

Extra fields from model_extra must be excluded from serialization by default
to prevent accidental exposure of sensitive values (e.g. tokens, secrets).
"""

import json
import warnings
from pathlib import Path

from hassette.config.classes import AppManifest


def _make_manifest(**overrides) -> AppManifest:
    """Create an AppManifest with sensible defaults, merging any overrides."""
    defaults = {
        "app_key": "test_app",
        "filename": "test_app.py",
        "class_name": "TestApp",
        "display_name": "Test App",
        "app_dir": Path("/tmp/apps"),
        "full_path": Path("/tmp/apps/test_app.py"),
    }
    defaults.update(overrides)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return AppManifest.model_validate(defaults)


class TestAppManifestModelDump:
    """model_dump and model_dump_json on AppManifest exclude extra fields."""

    def test_extra_fields_excluded_from_model_dump(self) -> None:
        manifest = _make_manifest(secret_token="super-secret", unknown_key="value")
        result = manifest.model_dump()

        assert "secret_token" not in result
        assert "unknown_key" not in result

    def test_declared_fields_still_present(self) -> None:
        manifest = _make_manifest(secret_token="super-secret")
        result = manifest.model_dump()

        assert result["app_key"] == "test_app"
        assert result["filename"] == "test_app.py"
        assert result["class_name"] == "TestApp"
        assert result["enabled"] is True

    def test_no_extras_works_normally(self) -> None:
        manifest = _make_manifest()
        result = manifest.model_dump()

        assert "app_key" in result
        assert "filename" in result

    def test_explicit_include_overrides(self) -> None:
        manifest = _make_manifest(secret_token="super-secret")
        result = manifest.model_dump(include={"app_key", "secret_token"})

        assert "app_key" in result
        assert "secret_token" in result

    def test_explicit_exclude_respected(self) -> None:
        manifest = _make_manifest(secret_token="super-secret")
        result = manifest.model_dump(exclude={"app_key"})

        assert "app_key" not in result
        assert "secret_token" not in result
        assert "filename" in result

    def test_model_dump_json_excludes_extras(self) -> None:
        manifest = _make_manifest(secret_token="super-secret", api_key="abc123")
        result = json.loads(manifest.model_dump_json())

        assert "secret_token" not in result
        assert "api_key" not in result
        assert result["app_key"] == "test_app"

    def test_model_dump_json_explicit_include(self) -> None:
        manifest = _make_manifest(secret_token="super-secret")
        result = json.loads(manifest.model_dump_json(include={"app_key", "secret_token"}))

        assert "app_key" in result
        assert "secret_token" in result

    def test_extras_still_accessible_via_model_extra(self) -> None:
        manifest = _make_manifest(secret_token="super-secret")

        assert manifest.model_extra is not None
        assert manifest.model_extra["secret_token"] == "super-secret"

    def test_include_none_still_excludes_extras(self) -> None:
        """include=None (default) must not bypass extra field exclusion."""
        manifest = _make_manifest(secret_token="super-secret")
        result = manifest.model_dump(include=None)

        assert "secret_token" not in result
        assert "app_key" in result

    def test_include_none_still_excludes_extras_json(self) -> None:
        """include=None (default) must not bypass extra field exclusion in JSON."""
        manifest = _make_manifest(secret_token="super-secret")
        result = json.loads(manifest.model_dump_json(include=None))

        assert "secret_token" not in result
        assert "app_key" in result

    def test_dict_shaped_exclude_with_extras(self) -> None:
        """Dict-shaped exclude (for nested field exclusion) must not TypeError."""
        manifest = _make_manifest(secret_token="super-secret")
        result = manifest.model_dump(exclude={"app_config": True})

        assert "app_config" not in result
        assert "secret_token" not in result
        assert "app_key" in result

    def test_dict_shaped_exclude_with_extras_json(self) -> None:
        """Dict-shaped exclude works for model_dump_json too."""
        manifest = _make_manifest(secret_token="super-secret")
        result = json.loads(manifest.model_dump_json(exclude={"app_config": True}))

        assert "app_config" not in result
        assert "secret_token" not in result
        assert "app_key" in result


class TestHassetteConfigModelDump:
    """model_dump on HassetteConfig excludes extra fields."""

    def test_extra_fields_excluded(self, test_config) -> None:
        if test_config.__pydantic_extra__ is None:
            test_config.__pydantic_extra__ = {}
        test_config.__pydantic_extra__["some_random_env"] = "leaked_value"

        try:
            result = test_config.model_dump()
            assert "some_random_env" not in result
        finally:
            test_config.__pydantic_extra__.pop("some_random_env", None)

    def test_declared_fields_present(self, test_config) -> None:
        result = test_config.model_dump()

        assert "token" in result
        assert "base_url" in result
        assert "log_level" in result

    def test_model_dump_json_excludes_extras(self, test_config) -> None:
        if test_config.__pydantic_extra__ is None:
            test_config.__pydantic_extra__ = {}
        test_config.__pydantic_extra__["secret_sauce"] = "hidden"

        try:
            result = json.loads(test_config.model_dump_json())
            assert "secret_sauce" not in result
            assert "base_url" in result
        finally:
            test_config.__pydantic_extra__.pop("secret_sauce", None)
