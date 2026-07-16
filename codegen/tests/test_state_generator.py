"""Unit tests for the state model generator."""

import py_compile
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.generators.states import _normalize_enum_prefixes, generate_state_model
from hassette_codegen.overrides import DomainOverride


class TestStateModelGenerator:
    def test_fan_domain(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            properties=[
                ExtractedProperty(name="percentage", python_type="int | None", has_default=True),
                ExtractedProperty(name="oscillating", python_type="bool | None", has_default=False),
                ExtractedProperty(name="preset_mode", python_type="str | None", has_default=True),
            ],
            features=[
                ExtractedEnum(
                    name="FanEntityFeature",
                    members=[("SET_SPEED", 1), ("OSCILLATE", 2), ("DIRECTION", 4)],
                )
            ],
        )
        output = generate_state_model(domain)
        assert "class FanEntityFeature(IntFlag):" in output
        assert "SET_SPEED = 1" in output
        assert "class FanAttributes(AttributesBase):" in output
        assert "class FanState(BoolBaseState):" in output
        assert 'domain: Literal["fan"]' in output
        assert "supports_set_speed" in output
        assert "supports_oscillate" in output
        assert "supports_direction" in output

    def test_sensor_domain_no_features(self) -> None:
        domain = ExtractedDomain(
            name="sensor",
            base_class="StringBaseState",
            properties=[
                ExtractedProperty(name="native_value", python_type="str | None", has_default=False),
            ],
            features=[],
            override=DomainOverride(domain="sensor", state_base_class="NumericBaseState"),
        )
        output = generate_state_model(domain)
        assert "IntFlag" not in output or "class" not in output.split("IntFlag")[0]
        assert "class SensorAttributes(AttributesBase):" in output
        assert "class SensorState(NumericBaseState):" in output
        assert "supports_" not in output

    def test_output_compiles(self) -> None:
        domain = ExtractedDomain(
            name="fan",
            base_class="BoolBaseState",
            properties=[
                ExtractedProperty(name="percentage", python_type="int | None", has_default=True),
            ],
            features=[
                ExtractedEnum(name="FanEntityFeature", members=[("SET_SPEED", 1)]),
            ],
        )
        output = generate_state_model(domain)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_fields_all_use_field_default_none(self) -> None:
        domain = ExtractedDomain(
            name="test",
            base_class="StringBaseState",
            properties=[
                ExtractedProperty(name="value", python_type="str | None", has_default=False),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert "Field(default=None)" in output

    def test_output_with_datetime_field_compiles(self) -> None:
        domain = ExtractedDomain(
            name="script",
            base_class="BoolBaseState",
            properties=[
                ExtractedProperty(name="last_triggered", python_type="ZonedDateTime | None", has_default=True),
                ExtractedProperty(name="mode", python_type="str | None", has_default=True),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(output)
            f.flush()
            py_compile.compile(f.name, doraise=True)

    def test_datetime_fields_get_validator(self) -> None:
        domain = ExtractedDomain(
            name="script",
            base_class="BoolBaseState",
            properties=[
                ExtractedProperty(name="last_triggered", python_type="ZonedDateTime | None", has_default=True),
                ExtractedProperty(name="mode", python_type="str | None", has_default=True),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert "field_validator" in output
        assert '"last_triggered"' in output
        assert "convert_datetime_str_to_tz" in output
        assert "_parse_datetime_fields" in output

    def test_mixed_union_datetime_fields_excluded_from_validator(self) -> None:
        domain = ExtractedDomain(
            name="sensor",
            base_class="NumericBaseState",
            properties=[
                ExtractedProperty(name="last_reset", python_type="ZonedDateTime | None", has_default=True),
                ExtractedProperty(
                    name="native_value", python_type="str | int | float | None | ZonedDateTime", has_default=True
                ),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert '"last_reset"' in output
        assert '"native_value"' not in output

    def test_no_validator_when_no_datetime_fields(self) -> None:
        domain = ExtractedDomain(
            name="switch",
            base_class="BoolBaseState",
            properties=[
                ExtractedProperty(name="device_class", python_type="str | None", has_default=True),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert "field_validator" not in output
        assert "convert_datetime_str_to_tz" not in output


class TestNormalizeEnumPrefixes:
    def test_fixes_geo_location_casing(self) -> None:
        enums = [ExtractedEnum(name="GeolocationEntityStateAttribute", members=[("A", "a")], kind="StrEnum")]
        result, renames = _normalize_enum_prefixes(enums, "GeoLocation")
        assert result[0].name == "GeoLocationEntityStateAttribute"
        assert renames == {"GeolocationEntityStateAttribute": "GeoLocationEntityStateAttribute"}

    def test_inserts_missing_entity_segment(self) -> None:
        enums = [
            ExtractedEnum(name="WaterHeaterCapabilityAttribute", members=[("A", "a")], kind="StrEnum"),
            ExtractedEnum(name="WaterHeaterStateAttribute", members=[("B", "b")], kind="StrEnum"),
        ]
        result, renames = _normalize_enum_prefixes(enums, "WaterHeater")
        assert result[0].name == "WaterHeaterEntityCapabilityAttribute"
        assert result[1].name == "WaterHeaterEntityStateAttribute"
        assert len(renames) == 2

    def test_leaves_correctly_named_enums_unchanged(self) -> None:
        enums = [ExtractedEnum(name="ClimateEntityStateAttribute", members=[("A", "a")], kind="StrEnum")]
        result, renames = _normalize_enum_prefixes(enums, "Climate")
        assert result[0].name == "ClimateEntityStateAttribute"
        assert renames == {}

    def test_leaves_standalone_enums_unchanged(self) -> None:
        enums = [
            ExtractedEnum(name="ColorMode", members=[("A", "a")], kind="StrEnum"),
            ExtractedEnum(name="HVACMode", members=[("B", "b")], kind="StrEnum"),
        ]
        result, renames = _normalize_enum_prefixes(enums, "Light")
        assert result[0].name == "ColorMode"
        assert result[1].name == "HVACMode"
        assert renames == {}

    def test_leaves_non_matching_prefix_unchanged(self) -> None:
        enums = [ExtractedEnum(name="TrackerEntityStateAttribute", members=[("A", "a")], kind="StrEnum")]
        result, renames = _normalize_enum_prefixes(enums, "DeviceTracker")
        assert result[0].name == "TrackerEntityStateAttribute"
        assert renames == {}

    def test_geo_location_integration(self) -> None:
        domain = ExtractedDomain(
            name="geo_location",
            base_class="StringBaseState",
            strenums=[
                ExtractedEnum(
                    name="GeolocationEntityStateAttribute",
                    members=[("SOURCE", "source")],
                    kind="StrEnum",
                )
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert "class GeoLocationEntityStateAttribute(StrEnum):" in output
        assert "GeolocationEntityStateAttribute" not in output

    def test_water_heater_integration(self) -> None:
        domain = ExtractedDomain(
            name="water_heater",
            base_class="StringBaseState",
            strenums=[
                ExtractedEnum(name="WaterHeaterCapabilityAttribute", members=[("A", "a")], kind="StrEnum"),
                ExtractedEnum(name="WaterHeaterStateAttribute", members=[("B", "b")], kind="StrEnum"),
            ],
            features=[],
        )
        output = generate_state_model(domain)
        assert "class WaterHeaterEntityCapabilityAttribute(StrEnum):" in output
        assert "class WaterHeaterEntityStateAttribute(StrEnum):" in output
        assert "WaterHeaterCapabilityAttribute" not in output
        assert "WaterHeaterStateAttribute" not in output
