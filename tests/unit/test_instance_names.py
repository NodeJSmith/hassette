"""Instance names: the one naming rule, its charset, and uniqueness across the config (#3095)."""

import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from hassette.config.classes import AppManifest
from hassette.config.config import validate_app_manifests
from hassette.exceptions import ConfigError

APP_DIR = Path("/tmp/apps")


def app_entry(app_key: str, config: Any = None, **overrides: Any) -> dict[str, Any]:
    """A cleaned app entry, as config loading hands it to manifest validation."""
    entry: dict[str, Any] = {
        "app_key": app_key,
        "filename": f"{app_key}.py",
        "class_name": "PresenceApp",
        "app_dir": APP_DIR,
        "full_path": APP_DIR / f"{app_key}.py",
        "config": config if config is not None else [],
    }
    entry.update(overrides)
    return entry


def manifest_names(manifest: AppManifest) -> list[str]:
    configs = manifest.app_config if isinstance(manifest.app_config, list) else [manifest.app_config]
    return [c["instance_name"] for c in configs]


def validate(entry: dict[str, Any]) -> AppManifest:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return AppManifest.model_validate(entry)


class TestConfiguredInstances:
    @pytest.mark.parametrize(
        "overrides",
        [{}, {"enabled": False}, {"autostart": False}],
        ids=["enabled", "disabled", "no_autostart"],
    )
    def test_section_without_config_fails_naming_the_section(self, overrides: dict[str, Any]) -> None:
        """A configured section needs a name even with no config, whether or not it would run."""
        with pytest.raises(ValidationError, match=r"app 'presence' instance 0 has no instance_name"):
            validate(app_entry("presence", **overrides))

    def test_list_entry_without_name_fails_naming_its_index(self) -> None:
        config = [{"instance_name": "upstairs"}, {"lights": ["light.kitchen"]}]
        with pytest.raises(ValidationError, match=r"app 'presence' instance 1 has no instance_name"):
            validate(app_entry("presence", config))

    def test_named_instances_keep_their_names(self) -> None:
        manifest = validate(app_entry("presence", [{"instance_name": "upstairs"}, {"instance_name": "downstairs"}]))
        assert manifest_names(manifest) == ["upstairs", "downstairs"]

    def test_single_config_table_is_one_named_instance(self) -> None:
        manifest = validate(app_entry("presence", {"instance_name": "hall", "lights": ["light.entry"]}))
        assert manifest_names(manifest) == ["hall"]

    @pytest.mark.parametrize(
        "name",
        ["Upstairs", "up-stairs", "upstairs_", "2nd_floor", "_upstairs", "PresenceApp.0", "a" * 129, ""],
    )
    def test_names_outside_the_charset_fail(self, name: str) -> None:
        with pytest.raises(ValidationError, match=r"app 'presence' instance 0"):
            validate(app_entry("presence", {"instance_name": name}))

    @pytest.mark.parametrize("name", ["a", "upstairs", "kitchen_lights_2", "a" * 128])
    def test_names_inside_the_charset_pass(self, name: str) -> None:
        assert manifest_names(validate(app_entry("presence", {"instance_name": name}))) == [name]

    def test_non_string_name_fails(self) -> None:
        with pytest.raises(ValidationError, match="non-string instance_name"):
            validate(app_entry("presence", {"instance_name": 123}))


class TestUniqueness:
    def test_duplicate_across_app_keys_fails_naming_both(self) -> None:
        entries = {
            "upstairs_lights": app_entry("upstairs_lights", {"instance_name": "lights"}),
            "downstairs_lights": app_entry("downstairs_lights", {"instance_name": "lights"}),
        }
        with pytest.raises(ConfigError) as exc_info:
            validate_app_manifests(entries)
        message = str(exc_info.value)
        assert "'lights'" in message
        assert "app 'upstairs_lights' instance 0" in message
        assert "app 'downstairs_lights' instance 0" in message

    def test_duplicate_within_one_app_fails(self) -> None:
        entries = {"presence": app_entry("presence", [{"instance_name": "hall"}, {"instance_name": "hall"}])}
        with pytest.raises(ConfigError, match=r"app 'presence' instance 0, app 'presence' instance 1"):
            validate_app_manifests(entries)

    def test_duplicate_with_a_disabled_section_fails(self) -> None:
        """A clash is caught at load, not when the dormant app is switched on."""
        entries = {
            "presence": app_entry("presence", {"instance_name": "hall"}),
            "presence_lab": app_entry("presence_lab", {"instance_name": "hall"}, enabled=False),
        }
        with pytest.raises(ConfigError, match="'hall'"):
            validate_app_manifests(entries)

    def test_distinct_names_pass(self) -> None:
        entries = {
            "presence": app_entry("presence", [{"instance_name": "upstairs"}, {"instance_name": "downstairs"}]),
            "porch": app_entry("porch", {"instance_name": "porch"}),
        }
        assert set(validate_app_manifests(entries)) == {"presence", "porch"}
