"""Tests for DI conversion error legibility and narrowed sensor shape validation.

Both changes live in `convert_state_dict_to_model` (`conversion/state_registry.py`), which the
dependency injection annotation converter (`conversion/annotation_converter.py:73`) calls directly
for a `D.StateNew[...]`-style annotation — bypassing `StateRegistry.conversion_with_error_handling`,
which is where failures normally get wrapped into a framework exception.
"""

import pytest
from pydantic import ValidationError

from hassette.conversion.state_registry import convert_state_dict_to_model
from hassette.exceptions import SensorShapeMismatchError, UnableToConvertAnnotatedStateError
from hassette.models.states.sensor import SensorState
from hassette.models.states.sensor_shapes import EnumSensorState, NumericSensorState
from hassette.test_utils.helpers import make_sensor_state_dict


class TestShapeMismatchRaises:
    """DI raises when a narrowed annotation disagrees with the entity's actual shape."""

    def test_mismatched_narrowed_annotation_raises_instead_of_coercing(self) -> None:
        """EnumSensorState against a temperature sensor would coerce '23.5' to a string with no
        error if unvalidated — coercion succeeding is exactly the damaging case shape validation
        exists to catch.
        """
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_temperature",
            state="23.5",
            device_class="temperature",
            unit_of_measurement="°F",
        )

        with pytest.raises(SensorShapeMismatchError) as exc_info:
            convert_state_dict_to_model(state_dict, EnumSensorState)

        err = exc_info.value
        assert err.entity_id == "sensor.zone_a_temperature"
        assert err.device_class == "temperature"
        assert err.state_class is EnumSensorState

    def test_matching_narrowed_annotation_still_converts(self) -> None:
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_temperature",
            state="23.5",
            device_class="temperature",
            unit_of_measurement="°F",
        )

        state = convert_state_dict_to_model(state_dict, NumericSensorState)

        assert isinstance(state, NumericSensorState)
        assert state.value == pytest.approx(23.5)

    def test_plain_sensor_state_annotation_unaffected(self) -> None:
        """A plain SensorState annotation makes no shape claim, so a temperature sensor converts
        regardless of what a narrowed accessor would have said about it.
        """
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_temperature",
            state="23.5",
            device_class="temperature",
            unit_of_measurement="°F",
        )

        state = convert_state_dict_to_model(state_dict, SensorState)

        assert isinstance(state, SensorState)
        assert state.value == "23.5"

    def test_unknown_shape_entity_does_not_raise(self) -> None:
        """An entity with no device_class, state_class, or unit_of_measurement classifies as
        SensorShape.UNKNOWN — no shape claim can be contradicted, so a narrowed annotation does
        not raise even though it makes a shape claim.
        """
        state_dict = make_sensor_state_dict(
            entity_id="sensor.zone_a_mystery",
            state="excellent",
        )

        state = convert_state_dict_to_model(state_dict, EnumSensorState)

        assert isinstance(state, EnumSensorState)
        assert state.value == "excellent"


class TestConversionFailureLegibility:
    """A failed DI conversion raises a framework exception naming the entity, its actual device
    class, and the annotated class, chaining the original ValidationError.
    """

    def test_validation_failure_wrapped_with_entity_context(self) -> None:
        # `options` matches the declared shape (device_class="enum" -> EnumSensorState), so this
        # exercises the ValidationError wrapping path, not the shape mismatch path — the
        # list[str] field rejects a bare string.
        state_dict = make_sensor_state_dict(
            entity_id="sensor.laundry_mode",
            state="eco",
            device_class="enum",
            options="not-a-list",
        )

        with pytest.raises(UnableToConvertAnnotatedStateError) as exc_info:
            convert_state_dict_to_model(state_dict, EnumSensorState)

        err = exc_info.value
        message = str(err)
        assert "sensor.laundry_mode" in message
        assert "enum" in message
        assert "EnumSensorState" in message
        assert err.entity_id == "sensor.laundry_mode"
        assert err.device_class == "enum"
        assert err.state_class is EnumSensorState
        assert isinstance(err.__cause__, ValidationError)
