"""Tests for the codec known-model coercion path.

Covers:
- The domain-states subscript path returns coerced typed values (bool, not "on")
  through state_manager.py's coerce_and_construct call site.
- A coercion failure on the state path raises UnableToConvertStateError with entity_id.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from hassette.exceptions import UnableToConvertStateError
from hassette.models.states.binary_sensor import BinarySensorState
from hassette.models.states.light import LightState
from hassette.state_manager.state_manager import DomainStates
from hassette.test_utils import make_light_state_dict, make_state_dict
from hassette.types import StateT


def domain_states_from(state_dict: dict[str, Any], model: type[StateT]) -> DomainStates[StateT]:
    """Build a DomainStates backed by a mock proxy returning the given state dict."""
    proxy = MagicMock()
    proxy.get_state.return_value = state_dict
    return DomainStates(proxy, model)


class TestCodecKnownModelTypedValues:
    """Domain-states subscript path returns codec-coerced typed values."""

    def test_light_on_yields_bool_true(self) -> None:
        """LightState (BoolBaseState) domain yields bool True, not the string 'on'."""
        ds = domain_states_from(make_light_state_dict("light.kitchen", "on"), LightState)
        state = ds["light.kitchen"]
        assert state.value is True
        assert isinstance(state.value, bool)

    def test_light_off_yields_bool_false(self) -> None:
        """LightState (BoolBaseState) domain yields bool False, not the string 'off'."""
        ds = domain_states_from(make_light_state_dict("light.kitchen", "off"), LightState)
        state = ds["light.kitchen"]
        assert state.value is False
        assert isinstance(state.value, bool)

    def test_binary_sensor_on_yields_bool_true(self) -> None:
        """BinarySensorState (BoolBaseState) domain yields bool True via codec path."""
        ds = domain_states_from(make_state_dict("binary_sensor.front_door", "on"), BinarySensorState)
        state = ds["binary_sensor.front_door"]
        assert state.value is True
        assert isinstance(state.value, bool)

    def test_unknown_state_yields_none_with_flag(self) -> None:
        """Unknown state is normalized to None before coercion; is_unknown flag is set."""
        ds = domain_states_from(make_light_state_dict("light.kitchen", "unknown"), LightState)
        state = ds["light.kitchen"]
        assert state.value is None
        assert state.is_unknown is True

    def test_unavailable_state_yields_none_with_flag(self) -> None:
        """Unavailable state is normalized to None before coercion; is_unavailable flag is set."""
        ds = domain_states_from(make_light_state_dict("light.kitchen", "unavailable"), LightState)
        state = ds["light.kitchen"]
        assert state.value is None
        assert state.is_unavailable is True


class TestCodecKnownModelCoercionFailure:
    """Coercion failure on the state path raises UnableToConvertStateError with entity_id."""

    def test_invalid_timestamp_raises_unable_to_convert_with_entity_id(self) -> None:
        """A state dict with invalid timestamp fields raises UnableToConvertStateError carrying entity_id."""
        bad_state = {
            "entity_id": "light.bad",
            "state": "on",
            "attributes": {},
            "last_changed": "NOT-A-TIMESTAMP",
            "last_updated": "NOT-A-TIMESTAMP",
            "context": {"id": None, "parent_id": None, "user_id": None},
        }
        ds = domain_states_from(bad_state, LightState)

        with pytest.raises(UnableToConvertStateError) as exc_info:
            ds["light.bad"]

        err = exc_info.value
        assert err.entity_id == "light.bad"
        assert err.state_class is LightState
