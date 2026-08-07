"""Unit tests for the TOML override system."""

from pathlib import Path

import pytest

from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.overrides import (
    DomainOverride,
    PropertyOverride,
    apply_property_overrides,
    get_override,
    load_overrides,
    validate_overrides,
)


class TestLoadOverrides:
    def test_loads_from_default_dir(self) -> None:
        overrides = load_overrides()
        assert "light" in overrides
        assert "media_player" in overrides

    def test_light_has_extra_imports(self) -> None:
        overrides = load_overrides()
        light = overrides["light"]
        assert "entity" in light.extra_imports
        assert any("Color" in imp for imp in light.extra_imports["entity"])

    def test_light_has_param_type_override(self) -> None:
        overrides = load_overrides()
        light = overrides["light"]
        assert "color_name" in light.param_type_overrides

    def test_media_player_has_renames(self) -> None:
        overrides = load_overrides()
        mp = overrides["media_player"]
        assert mp.service_param_renames.get("media_content_type") == "media_type"

    def test_state_base_class_override(self, tmp_path: Path) -> None:
        toml = tmp_path / "sensor.toml"
        toml.write_text('state_base_class = "NumericBaseState"\n')
        overrides = load_overrides(tmp_path)
        assert overrides["sensor"].state_base_class == "NumericBaseState"

    def test_get_override_returns_none_for_unknown(self) -> None:
        overrides = load_overrides()
        assert get_override(overrides, "nonexistent_domain") is None

    def test_loads_from_custom_dir(self, tmp_path: Path) -> None:
        toml = tmp_path / "test.toml"
        toml.write_text('state_base_class = "BoolBaseState"\n')
        overrides = load_overrides(tmp_path)
        assert "test" in overrides
        assert overrides["test"].state_base_class == "BoolBaseState"


class TestValidateOverrides:
    def test_warns_on_unknown_domain(self, capsys: pytest.CaptureFixture[str]) -> None:
        overrides = {"fake_domain": DomainOverride(domain="fake_domain")}
        validate_overrides(overrides, {"light", "fan"})


class TestApplyPropertyOverridesRemove:
    def test_removes_matching_property(self) -> None:
        properties = [
            ExtractedProperty(name="native_value", python_type="str | None", has_default=True),
            ExtractedProperty(name="state_class", python_type="str | None", has_default=True),
        ]
        overrides = [PropertyOverride(name="native_value", remove=True)]

        result = apply_property_overrides(properties, overrides)

        assert [p.name for p in result] == ["state_class"]

    def test_removes_multiple_properties(self) -> None:
        properties = [
            ExtractedProperty(name="native_value", python_type="str | None", has_default=True),
            ExtractedProperty(name="native_unit_of_measurement", python_type="str | None", has_default=True),
            ExtractedProperty(name="suggested_display_precision", python_type="int | None", has_default=True),
            ExtractedProperty(name="state_class", python_type="str | None", has_default=True),
        ]
        overrides = [
            PropertyOverride(name="native_value", remove=True),
            PropertyOverride(name="native_unit_of_measurement", remove=True),
            PropertyOverride(name="suggested_display_precision", remove=True),
        ]

        result = apply_property_overrides(properties, overrides)

        assert [p.name for p in result] == ["state_class"]

    def test_does_not_mutate_input_list(self) -> None:
        properties = [ExtractedProperty(name="native_value", python_type="str | None", has_default=True)]
        overrides = [PropertyOverride(name="native_value", remove=True)]

        result = apply_property_overrides(properties, overrides)

        assert len(properties) == 1
        assert result is not properties

    def test_warns_when_remove_target_missing(self, capsys: pytest.CaptureFixture[str]) -> None:
        properties = [ExtractedProperty(name="state_class", python_type="str | None", has_default=True)]
        overrides = [PropertyOverride(name="nonexistent_field", remove=True)]

        result = apply_property_overrides(properties, overrides)

        assert [p.name for p in result] == ["state_class"]
        captured = capsys.readouterr()
        assert "nonexistent_field" in captured.err
        assert "WARNING" in captured.err
