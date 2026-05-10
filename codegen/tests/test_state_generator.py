"""Unit tests for the state model generator."""

import py_compile
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hassette_codegen.domain_data import ExtractedDomain
from hassette_codegen.extractors.features import ExtractedEnum
from hassette_codegen.extractors.properties import ExtractedProperty
from hassette_codegen.generators.states import generate_state_model
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
