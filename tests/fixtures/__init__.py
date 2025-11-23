"""Test fixtures for state proxy and states testing."""

from .state_fixtures import (
    make_light_state_dict,
    make_sensor_state_dict,
    make_state_change_event,
    make_state_dict,
    make_switch_state_dict,
)

__all__ = [
    "make_light_state_dict",
    "make_sensor_state_dict",
    "make_state_change_event",
    "make_state_dict",
    "make_switch_state_dict",
]
