"""Tests for custom state models and custom type converters through the conversion pipeline.

Covers the user-facing patterns documented in custom-states.md and
dependency-injection.md: defining custom state classes with typed attributes,
registering custom type converters, and verifying that the full codec pipeline
handles them correctly.
"""

from enum import StrEnum
from typing import Any, ClassVar, Literal

import pytest
from pydantic import Field

from hassette.conversion import STATE_REGISTRY, TYPE_REGISTRY, convert_state_dict_to_model, register_type_converter_fn
from hassette.conversion.type_registry import TypeRegistry
from hassette.exceptions import UnableToConvertValueError
from hassette.models.states.base import AttributesBase, BaseState, BoolBaseState, NumericBaseState, StringBaseState
from hassette.test_utils import make_state_dict, make_typed_state


@pytest.fixture(autouse=True)
def _isolate_type_registry():
    """Restore TypeRegistry after tests that register custom converters."""
    snap = dict(TypeRegistry.conversion_map)
    yield
    TypeRegistry.conversion_map.clear()
    TypeRegistry.conversion_map.update(snap)


class PlantAttributes(AttributesBase):
    moisture: int | None = Field(default=None)
    conductivity: int | None = Field(default=None)
    temperature: float | None = Field(default=None)


class PlantState(StringBaseState):
    domain: Literal["plant"]
    attributes: PlantAttributes


class CustomBoolState(BoolBaseState):
    domain: Literal["custom_bool_test"]


class CustomNumericState(NumericBaseState):
    domain: Literal["custom_numeric_test"]


class RobotMode(StrEnum):
    IDLE = "idle"
    CLEANING = "cleaning"
    RETURNING = "returning"
    ERROR = "error"


class RobotState(BaseState[RobotMode | None]):
    domain: Literal["custom_robot_test"]
    value_type: ClassVar[type[Any] | tuple[type[Any], ...]] = (RobotMode, type(None))


class TestCustomStateWithAttributes:
    """Custom state models with typed AttributesBase subclasses."""

    def test_model_validate_populates_typed_attributes(self) -> None:
        raw = make_state_dict("plant.fern", "ok", {"moisture": 42, "conductivity": 300, "temperature": 22.5})
        state = PlantState.model_validate(raw)
        assert type(state) is PlantState
        assert isinstance(state.attributes, PlantAttributes)
        assert state.attributes.moisture == 42
        assert state.attributes.conductivity == 300
        assert state.attributes.temperature == 22.5

    def test_try_convert_state_populates_typed_attributes(self) -> None:
        raw = make_state_dict("plant.fern", "ok", {"moisture": 42, "conductivity": 300})
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is PlantState
        assert isinstance(state.attributes, PlantAttributes)
        assert state.attributes.moisture == 42
        assert state.attributes.conductivity == 300

    def test_make_typed_state_populates_typed_attributes(self) -> None:
        raw = make_state_dict("plant.fern", "ok", {"moisture": 42})
        state = make_typed_state(PlantState, raw)
        assert type(state) is PlantState
        assert isinstance(state.attributes, PlantAttributes)
        assert state.attributes.moisture == 42

    def test_extra_attributes_accessible_via_extras(self) -> None:
        raw = make_state_dict("plant.fern", "ok", {"moisture": 42, "battery": 85})
        state = PlantState.model_validate(raw)
        assert state.attributes.moisture == 42
        assert state.attributes.extra("battery") == 85

    def test_missing_optional_attributes_default_to_none(self) -> None:
        raw = make_state_dict("plant.fern", "ok", {})
        state = PlantState.model_validate(raw)
        assert state.attributes.moisture is None
        assert state.attributes.conductivity is None
        assert state.attributes.temperature is None


class TestCustomStateValueCoercion:
    """Custom state models using built-in base classes get correct value coercion."""

    def test_custom_bool_state_coerces_on_to_true(self) -> None:
        raw = make_state_dict("custom_bool_test.switch1", "on")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomBoolState
        assert state.value is True

    def test_custom_bool_state_coerces_off_to_false(self) -> None:
        raw = make_state_dict("custom_bool_test.switch1", "off")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomBoolState
        assert state.value is False

    def test_custom_numeric_state_coerces_string_to_number(self) -> None:
        raw = make_state_dict("custom_numeric_test.gauge", "42.5")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomNumericState
        assert state.value == 42.5
        assert isinstance(state.value, float)

    def test_custom_numeric_state_integer_string(self) -> None:
        raw = make_state_dict("custom_numeric_test.gauge", "100")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomNumericState
        assert state.value == 100
        assert isinstance(state.value, int)

    def test_custom_state_unknown_normalization(self) -> None:
        raw = make_state_dict("custom_bool_test.switch1", "unknown")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomBoolState
        assert state.value is None
        assert state.is_unknown is True

    def test_custom_state_unavailable_normalization(self) -> None:
        raw = make_state_dict("custom_numeric_test.gauge", "unavailable")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is CustomNumericState
        assert state.value is None
        assert state.is_unavailable is True


class TestCustomEnumValueType:
    """Custom state model with a user-defined StrEnum value_type and registered converter."""

    def test_custom_enum_coercion_via_model_validate(self) -> None:
        @register_type_converter_fn
        def str_to_robot_mode(value: str) -> RobotMode:
            return RobotMode(value.lower())

        raw = make_state_dict("custom_robot_test.vacuum", "cleaning")
        state = RobotState.model_validate(raw)
        assert state.value == RobotMode.CLEANING
        assert isinstance(state.value, RobotMode)

    def test_custom_enum_coercion_via_try_convert_state(self) -> None:
        @register_type_converter_fn
        def str_to_robot_mode(value: str) -> RobotMode:
            return RobotMode(value.lower())

        raw = make_state_dict("custom_robot_test.vacuum", "idle")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is RobotState
        assert state.value == RobotMode.IDLE

    def test_custom_enum_unknown_yields_none(self) -> None:
        @register_type_converter_fn
        def str_to_robot_mode(value: str) -> RobotMode:
            return RobotMode(value.lower())

        raw = make_state_dict("custom_robot_test.vacuum", "unknown")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is RobotState
        assert state.value is None
        assert state.is_unknown is True

    def test_without_converter_uses_constructor_fallback(self) -> None:
        assert (str, RobotMode) not in TypeRegistry.conversion_map
        raw = make_state_dict("custom_robot_test.vacuum", "cleaning")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is RobotState
        assert state.value == RobotMode.CLEANING


class TestRegisterTypeConverterFn:
    """The @register_type_converter_fn decorator registers converters in TypeRegistry."""

    def test_bare_decorator_registers_converter(self) -> None:
        @register_type_converter_fn
        def str_to_robot_mode(value: str) -> RobotMode:
            return RobotMode(value.lower())

        result = TYPE_REGISTRY.convert("cleaning", RobotMode)
        assert result == RobotMode.CLEANING

    def test_decorator_with_error_message(self) -> None:
        @register_type_converter_fn(error_message="'{value}' is not a valid RobotMode")
        def str_to_robot_mode(value: str) -> RobotMode:
            return RobotMode(value.lower())

        with pytest.raises(UnableToConvertValueError, match="'INVALID' is not a valid RobotMode"):
            TYPE_REGISTRY.convert("INVALID", RobotMode)

    def test_converter_is_used_by_state_pipeline(self) -> None:
        calls: list[str] = []

        @register_type_converter_fn
        def str_to_robot_mode(value: str) -> RobotMode:
            calls.append(value)
            return RobotMode(value.lower())

        raw = make_state_dict("custom_robot_test.vacuum", "returning")
        state = convert_state_dict_to_model(raw, RobotState)
        assert state.value == RobotMode.RETURNING
        assert "returning" in calls


class TestConvertStateDictToModel:
    """Direct convert_state_dict_to_model calls with custom state models."""

    def test_extracts_domain_from_entity_id(self) -> None:
        raw = make_state_dict("plant.fern", "ok")
        state = convert_state_dict_to_model(raw, PlantState)
        assert state.domain == "plant"

    def test_passes_through_already_constructed_instance(self) -> None:
        raw = make_state_dict("plant.fern", "ok")
        first = convert_state_dict_to_model(raw, PlantState)
        second = convert_state_dict_to_model(first, PlantState)
        assert first is second

    def test_rejects_non_dict_non_model_input(self) -> None:
        with pytest.raises(TypeError, match="expected dict"):
            convert_state_dict_to_model("not a dict", PlantState)
