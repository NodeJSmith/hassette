"""Mapping values convert into pydantic models and dataclasses on the dependency injection path."""

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from hassette import D
from hassette.bus.injection import ParameterInjector
from hassette.conversion import ANNOTATION_CONVERTER
from hassette.events.hass.hass import create_event_from_hass
from hassette.exceptions import DependencyResolutionError, UnableToConvertValueError
from hassette.utils.type_utils import get_typed_signature


class RoomModel(BaseModel):
    room: str
    count: int = 0


@dataclass
class RoomData:
    room: str
    count: int = 0


def custom_event(data: dict[str, Any]) -> Any:
    """A custom HA event, built the way the websocket receive path builds it."""
    return create_event_from_hass(
        {
            "type": "event",
            "id": 1,
            "event": {
                "event_type": "my_custom_event",
                "data": data,
                "origin": "LOCAL",
                "time_fired": "2026-11-17T12:00:00+00:00",
                "context": {"id": "ctx", "parent_id": None, "user_id": None},
            },
        }
    )


@pytest.mark.parametrize("target", [RoomModel, RoomData], ids=["pydantic", "dataclass"])
def test_mapping_converts_into_model(target: type):
    """A dict validates into a pydantic model or dataclass, with lax coercion of field values."""
    result = ANNOTATION_CONVERTER.convert({"room": "kitchen", "count": "3"}, target)
    assert result == target(room="kitchen", count=3)


@pytest.mark.parametrize("target", [RoomModel, RoomData], ids=["pydantic", "dataclass"])
def test_missing_required_field_raises_naming_field(target: type):
    """A dict missing a required field raises pydantic's error, which names the field."""
    with pytest.raises(ValidationError, match="room"):
        ANNOTATION_CONVERTER.convert({"count": 1}, target)


def test_list_of_mappings_converts_into_list_of_models():
    """Container converters recurse into the mapping branch per element."""
    result = ANNOTATION_CONVERTER.convert([{"room": "a"}, {"room": "b"}], list[RoomData])
    assert result == [RoomData(room="a"), RoomData(room="b")]


def test_optional_model_union_reports_the_model_arm_error():
    """When every arm of `Model | None` fails, the message carries the model arm's field error."""
    with pytest.raises(UnableToConvertValueError, match=r"(?s)RoomModel.*room"):
        ANNOTATION_CONVERTER.convert({"count": 1}, RoomModel | None)


def test_dict_or_model_union_keeps_the_dict():
    """`dict | Model` already matches a dict, so it passes through unconverted."""
    value = {"room": "kitchen"}
    assert ANNOTATION_CONVERTER.convert(value, dict | RoomModel) is value


def test_event_data_converts_custom_hass_event_into_model():
    """`D.EventData[Model]` on a custom HA event delivers the event's JSON data as the model."""

    def handler(data: D.EventData[RoomData]) -> None:
        pass

    injector = ParameterInjector("handler", get_typed_signature(handler))
    kwargs = injector.inject_parameters(custom_event({"room": "kitchen"}))
    assert kwargs == {"data": RoomData(room="kitchen")}


def test_event_data_invalid_custom_hass_event_names_the_field():
    """Invalid data skips the handler with a DependencyResolutionError naming the field."""

    def handler(data: D.EventData[RoomData]) -> None:
        pass

    injector = ParameterInjector("handler", get_typed_signature(handler))
    with pytest.raises(DependencyResolutionError, match="room"):
        injector.inject_parameters(custom_event({"count": 1}))
