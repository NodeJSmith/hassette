"""hassette_message events built from what HA sends, and `D.MessageData` on missing or malformed data."""

from dataclasses import dataclass
from typing import Any

import pytest

from hassette import D
from hassette.bus.injection import ParameterInjector
from hassette.events import HassetteMessageEvent
from hassette.events.hass.hass import MissingPayloadFieldsError
from hassette.exceptions import DependencyResolutionError
from hassette.testing._factories import create_hass_event
from hassette.utils.type_utils import get_typed_signature


@dataclass
class TrackerDone:
    room: str


def message_injector() -> ParameterInjector:
    def handler(data: D.MessageData[TrackerDone]) -> None:
        pass

    return ParameterInjector("handler", get_typed_signature(handler))


def test_message_without_data_key_defaults_to_empty_mapping():
    """An event fired without a `data` key gets `{}`, as hass-hassette's contract defaults it."""
    event = create_hass_event("hassette_message", {"name": "tracker_done"})

    assert isinstance(event, HassetteMessageEvent)
    assert event.payload.data.name == "tracker_done"
    assert event.payload.data.data == {}


def test_message_without_name_cannot_be_built():
    """An event fired without `name` raises naming the missing field, so dispatch drops and logs it."""
    with pytest.raises(MissingPayloadFieldsError) as exc_info:
        create_hass_event("hassette_message", {"data": {"room": "kitchen"}})

    assert exc_info.value.payload_name == "HassetteMessagePayload"
    assert exc_info.value.missing == ("name",)


@pytest.mark.parametrize("data", [None, ["kitchen"]], ids=["null", "non_mapping"])
def test_message_data_that_is_not_a_mapping_skips_the_handler(data: Any):
    """`data: null` or a non-mapping `data` isn't defaulted; extracting it fails, which skips the handler."""
    event = create_hass_event("hassette_message", {"name": "tracker_done", "data": data})

    with pytest.raises(DependencyResolutionError):
        message_injector().inject_parameters(event)


def test_message_data_missing_required_field_names_it():
    """A message sent without `data` validates `{}`, and the error names the required field."""
    event = create_hass_event("hassette_message", {"name": "tracker_done"})

    with pytest.raises(DependencyResolutionError, match="room"):
        message_injector().inject_parameters(event)
