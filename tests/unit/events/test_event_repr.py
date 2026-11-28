"""Tests for Event.__repr__."""

from hassette.events.base import Event, HassettePayload
from hassette.events.hassette import HassetteSimpleEvent
from hassette.types import Topic


def test_event_repr_shows_subclass_name_and_topic() -> None:
    event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED)

    r = repr(event)

    assert r.startswith(f"HassetteSimpleEvent(topic={Topic.HASSETTE_EVENT_APP_LOAD_COMPLETED.value}, payload=")
    assert repr(event.payload) in r


def test_event_repr_omits_websocket_generation() -> None:
    event = Event(topic="custom.topic", payload=HassettePayload(data=None), websocket_generation=3)

    r = repr(event)

    assert r.startswith("Event(topic=custom.topic, payload=")
    assert "websocket_generation" not in r
