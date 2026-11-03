"""Tests for the typed `event_type` attribute on `EventState`."""

from hassette.conversion.state_registry import convert_state_dict_to_model
from hassette.models.states.event import EventState
from hassette.testing import make_state_dict


def test_event_type_read_from_fired_event_payload() -> None:
    state_dict = make_state_dict(
        "event.hallway_button",
        "2026-11-03T12:00:00.000+00:00",
        attributes={
            "device_class": "button",
            "event_types": ["press_start", "press_end"],
            "event_type": "press_end",
            "friendly_name": "Hallway Button",
        },
    )

    state = convert_state_dict_to_model(state_dict, EventState)

    assert isinstance(state, EventState)
    assert state.attributes.event_type == "press_end"


def test_event_type_none_when_attribute_absent() -> None:
    state_dict = make_state_dict(
        "event.hallway_button",
        "unavailable",
        attributes={"device_class": "button", "event_types": ["press_start", "press_end"]},
    )

    state = convert_state_dict_to_model(state_dict, EventState)

    assert isinstance(state, EventState)
    assert state.attributes.event_type is None
