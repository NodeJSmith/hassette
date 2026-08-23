"""Unit tests for the state model generator."""

import ast

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.generators.states import _normalize_enum_prefixes, generate_state_model
from hassette_codegen.overrides import DomainOverride

from .conftest import assert_compiles


def _datetime_domain() -> ExtractedDomain:
    """Build a test domain with a datetime property to exercise datetime-specific codegen."""
    return ExtractedDomain(
        name="script",
        base_class="BoolBaseState",
        properties=[
            ExtractedProperty(name="last_triggered", python_type="ZonedDateTime | None", has_default=True),
            ExtractedProperty(name="mode", python_type="str | None", has_default=True),
        ],
        features=[],
    )


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
        assert_compiles(generate_state_model(domain))

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
        assert_compiles(generate_state_model(_datetime_domain()))

    def test_datetime_fields_get_validator(self) -> None:
        output = generate_state_model(_datetime_domain())
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


class TestStateModelEscaping:
    """StrEnum member values and the domain name are HA-derived and land in literal positions."""

    @staticmethod
    def _enum_member_values(output: str, enum_name: str) -> list[object]:
        module = ast.parse(output)
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == enum_name)
        assigns = [n for n in cls.body if isinstance(n, ast.Assign)]
        for assign in assigns:
            # A member whose value parsed as anything but a literal means the input became code.
            assert isinstance(assign.value, ast.Constant), ast.dump(assign.value)
        return [assign.value.value for assign in assigns]  # pyright: ignore[reportAttributeAccessIssue]

    def test_strenum_member_value_stays_one_literal(self) -> None:
        hostile = 'off"\n    INJECTED = "yes'
        domain = ExtractedDomain(
            name="fan",
            base_class="StringBaseState",
            strenums=[ExtractedEnum(name="FanMode", members=[("OFF", hostile)], kind="StrEnum")],
        )

        assert self._enum_member_values(generate_state_model(domain), "FanMode") == [hostile]

    def test_intflag_member_value_is_not_an_arbitrary_expression(self) -> None:
        # The extractor only yields ints today, so this pins the unquoted template position rather
        # than a reachable input: a string here used to render as bare source.
        domain = ExtractedDomain(
            name="fan",
            base_class="StringBaseState",
            features=[ExtractedEnum(name="FanEntityFeature", members=[("EVIL", "__import__('os')")])],
        )

        assert self._enum_member_values(generate_state_model(domain), "FanEntityFeature") == ["__import__('os')"]

    def test_domain_renders_as_one_literal(self) -> None:
        domain = ExtractedDomain(name="fan", base_class="StringBaseState")
        module = ast.parse(generate_state_model(domain))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "FanState")
        annotation = next(n for n in cls.body if isinstance(n, ast.AnnAssign)).annotation

        assert isinstance(annotation, ast.Subscript)
        assert isinstance(annotation.slice, ast.Constant)
        assert annotation.slice.value == "fan"
