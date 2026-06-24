"""Characterization pin for state-conversion typed output.

Most test classes pin the direct model_validate path. TestTryConvertStateEntryPoint
pins the STATE_REGISTRY.try_convert_state codec path (domain resolution + type
coercion). If any assertion fails, the conversion produced a different typed value
than the expected golden output.

Write golden values from observation, not from calling the same code path twice.
"""

from typing import Literal

from whenever import Time, ZonedDateTime

from hassette.conversion import STATE_REGISTRY
from hassette.models.states.base import TimeBaseState
from hassette.models.states.binary_sensor import BinarySensorState
from hassette.models.states.input import InputButtonState, InputDatetimeState, InputNumberState
from hassette.models.states.light import LightState
from hassette.models.states.number import NumberState
from hassette.models.states.sensor import SensorState
from hassette.test_utils import make_state_dict, make_typed_state


class TestBoolValueTypeFamily:
    """Bool value_type family: value_type = (bool, type(None)). 'on' -> True, 'off' -> False."""

    def test_light_on_yields_true(self) -> None:
        raw = make_state_dict("light.kitchen", "on")
        state = LightState.model_validate(raw)
        assert state.value is True
        assert isinstance(state.value, bool)
        assert state.is_unknown is False
        assert state.is_unavailable is False

    def test_light_off_yields_false(self) -> None:
        raw = make_state_dict("light.kitchen", "off")
        state = LightState.model_validate(raw)
        assert state.value is False
        assert isinstance(state.value, bool)

    def test_binary_sensor_on_yields_true(self) -> None:
        raw = make_state_dict("binary_sensor.front_door", "on")
        state = BinarySensorState.model_validate(raw)
        assert state.value is True
        assert isinstance(state.value, bool)

    def test_binary_sensor_off_yields_false(self) -> None:
        raw = make_state_dict("binary_sensor.front_door", "off")
        state = BinarySensorState.model_validate(raw)
        assert state.value is False
        assert isinstance(state.value, bool)


class TestStringValueTypeFamily:
    """String value_type family: value_type = (str, type(None)). Raw string preserved as-is."""

    def test_sensor_numeric_string_stays_as_string(self) -> None:
        """SensorState uses StringBaseState — the value stays a str, not a float."""
        raw = make_state_dict("sensor.outdoor_temperature", "23.5")
        state = SensorState.model_validate(raw)
        assert state.value == "23.5"
        assert isinstance(state.value, str)

    def test_sensor_text_value(self) -> None:
        raw = make_state_dict("sensor.door_status", "open")
        state = SensorState.model_validate(raw)
        assert state.value == "open"
        assert isinstance(state.value, str)


class TestNumericValueTypeFamily:
    """Numeric value_type family: coercion tries int, then float, then Decimal."""

    def test_number_float_string_yields_float(self) -> None:
        raw = make_state_dict("number.brightness", "23.5")
        state = NumberState.model_validate(raw)
        assert state.value == 23.5
        assert isinstance(state.value, float)
        assert not isinstance(state.value, int)

    def test_number_integer_string_yields_int(self) -> None:
        raw = make_state_dict("number.count", "5")
        state = NumberState.model_validate(raw)
        assert state.value == 5
        assert isinstance(state.value, int)

    def test_input_number_float_zero_yields_float(self) -> None:
        raw = make_state_dict("input_number.slider", "42.0")
        state = make_typed_state(InputNumberState, raw)
        assert state.value == 42.0
        assert isinstance(state.value, float)


class TestDateTimeValueTypeFamily:
    """DateTime value_type family: ISO datetime string -> ZonedDateTime (converted to system tz)."""

    def test_input_button_iso_datetime_yields_zoned_datetime(self) -> None:
        raw = make_state_dict("input_button.test", "2024-01-15T10:30:00+00:00")
        state = make_typed_state(InputButtonState, raw)
        assert isinstance(state.value, ZonedDateTime)
        # The UTC offset is converted to system tz; verify the instant is correct.
        assert state.value.to_instant() == ZonedDateTime.parse_iso("2024-01-15T10:30:00+00:00[UTC]").to_instant()

    def test_input_datetime_iso_datetime_yields_zoned_datetime(self) -> None:
        raw = make_state_dict(
            "input_datetime.wake_up",
            "2024-06-01T08:00:00+00:00",
            attributes={"has_date": True, "has_time": True},
        )
        state = make_typed_state(InputDatetimeState, raw)
        assert isinstance(state.value, ZonedDateTime)


class TestTimeValueTypeFamily:
    """Time value_type family: ISO time string -> whenever.Time. Uses a throwaway subclass."""

    def test_time_iso_string_yields_time_object(self) -> None:
        class TimeDomainState(TimeBaseState):
            domain: Literal["test_time_domain"]  # pyright: ignore[reportIncompatibleVariableOverride]

        raw = make_state_dict("test_time_domain.alarm", "10:30:00")
        state = TimeDomainState.model_validate(raw)
        assert isinstance(state.value, Time)
        assert state.value == Time(10, 30, 0)


class TestUnknownUnavailableNormalization:
    """unknown/unavailable normalization must happen before value coercion."""

    def test_bool_domain_unknown_yields_none_with_flag(self) -> None:
        raw = make_state_dict("light.kitchen", "unknown")
        state = LightState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is True
        assert state.is_unavailable is False

    def test_bool_domain_unavailable_yields_none_with_flag(self) -> None:
        raw = make_state_dict("light.kitchen", "unavailable")
        state = LightState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is False
        assert state.is_unavailable is True

    def test_numeric_domain_unknown_yields_none_with_flag(self) -> None:
        """unknown is set to None before numeric coercion — never tries to coerce "unknown" as a number."""
        raw = make_state_dict("number.brightness", "unknown")
        state = NumberState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is True
        assert state.is_unavailable is False

    def test_numeric_domain_unavailable_yields_none_with_flag(self) -> None:
        raw = make_state_dict("number.brightness", "unavailable")
        state = NumberState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is False
        assert state.is_unavailable is True

    def test_datetime_domain_unknown_yields_none_with_flag(self) -> None:
        raw = make_state_dict("input_button.test", "unknown")
        state = InputButtonState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is True

    def test_string_domain_unknown_yields_none_with_flag(self) -> None:
        raw = make_state_dict("sensor.outdoor_temperature", "unknown")
        state = SensorState.model_validate(raw)
        assert state.value is None
        assert state.is_unknown is True

    def test_string_domain_unavailable_yields_none_with_flag(self) -> None:
        raw = make_state_dict("sensor.outdoor_temperature", "unavailable")
        state = SensorState.model_validate(raw)
        assert state.value is None
        assert state.is_unavailable is True


class TestTryConvertStateEntryPoint:
    """try_convert_state entry point: pins domain resolution + BaseState fallback path."""

    def test_light_on_via_registry(self) -> None:
        raw = make_state_dict("light.kitchen", "on")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is LightState
        assert state.value is True

    def test_sensor_string_via_registry(self) -> None:
        raw = make_state_dict("sensor.outdoor_temperature", "23.5")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is SensorState
        assert state.value == "23.5"
        assert isinstance(state.value, str)

    def test_number_float_via_registry(self) -> None:
        raw = make_state_dict("number.brightness", "23.5")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert type(state) is NumberState
        assert state.value == 23.5
        assert isinstance(state.value, float)

    def test_unknown_light_via_registry(self) -> None:
        raw = make_state_dict("light.kitchen", "unknown")
        state = STATE_REGISTRY.try_convert_state(raw)
        assert state.value is None
        assert state.is_unknown is True
