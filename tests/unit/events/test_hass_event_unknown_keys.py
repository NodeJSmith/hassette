"""Typed Home Assistant event payloads ignore keys a newer HA release adds (issue #3949)."""

import logging
from typing import Any, cast
from uuid import uuid4

import pytest

import hassette.events.hass.hass as hass_events
import hassette.utils.date_utils as date_utils
from hassette.events import (
    AutomationTriggeredEvent,
    ComponentLoadedEvent,
    HassEventEnvelopeDict,
    create_event_from_hass,
)
from hassette.testing._factories import create_hass_event

# One entry per typed branch in create_event_from_hass; add a new typed event type here too.
MINIMAL_EVENT_DATA: dict[str, dict[str, Any]] = {
    "state_changed": {"entity_id": "light.kitchen", "old_state": None, "new_state": None},
    "call_service": {"domain": "light", "service": "turn_on"},
    "component_loaded": {"component": "light"},
    "service_registered": {"domain": "light", "service": "turn_on"},
    "service_removed": {"domain": "light", "service": "turn_on"},
    "logbook_entry": {"name": "Kitchen", "message": "turned on"},
    "user_added": {"user_id": "abc"},
    "user_removed": {"user_id": "abc"},
    "automation_triggered": {"name": "Morning", "entity_id": "automation.morning"},
    "script_started": {"name": "Bedtime", "entity_id": "script.bedtime"},
}


@pytest.fixture(autouse=True)
def fresh_reported_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the once-per-key log dedupe set from other tests."""
    monkeypatch.setattr(hass_events, "reported_unknown_keys", set())


@pytest.mark.parametrize("event_type", sorted(MINIMAL_EVENT_DATA))
def test_typed_payload_ignores_unknown_key(event_type: str) -> None:
    """A key the payload doesn't declare is dropped instead of failing the event."""
    event = create_hass_event(event_type, {**MINIMAL_EVENT_DATA[event_type], "added_in_future_ha": 1})

    assert event.payload.event_type == event_type
    assert not hasattr(event.payload.data, "added_in_future_ha")


def test_automation_triggered_parses_ha_2026_11_shape() -> None:
    """HA 2026.11 sends item_id and run_id; both land on the typed payload."""
    event = create_hass_event(
        "automation_triggered",
        {
            "name": "Morning",
            "entity_id": "automation.morning",
            "source": "state of binary_sensor.motion",
            "item_id": "1700000000000",
            "run_id": "01JC5Z6K8Y2Q3R4S5T6V7W8X9Y",
        },
    )

    assert isinstance(event, AutomationTriggeredEvent)
    assert event.payload.data.item_id == "1700000000000"
    assert event.payload.data.run_id == "01JC5Z6K8Y2Q3R4S5T6V7W8X9Y"


def test_context_ignores_unknown_key() -> None:
    """A new key in the event context doesn't fail the event."""
    context_id = str(uuid4())
    # The extra context key is the point of the test, so the envelope can't match HassEventEnvelopeDict's shape.
    envelope = cast(
        "HassEventEnvelopeDict",
        {
            "id": 1,
            "type": "event",
            "event": {
                "event_type": "component_loaded",
                "data": {"component": "light"},
                "origin": "LOCAL",
                "time_fired": date_utils.now().format_iso(),
                "context": {"id": context_id, "parent_id": None, "user_id": None, "added_in_future_ha": 1},
            },
        },
    )
    event = create_event_from_hass(envelope)

    assert isinstance(event, ComponentLoadedEvent)
    assert event.payload.context.id == context_id


def test_unknown_key_logged_once_by_name_without_value(caplog: pytest.LogCaptureFixture) -> None:
    """Each unknown key is reported once per payload type, by name only."""
    data = {**MINIMAL_EVENT_DATA["user_added"], "secret_key": "secret-value"}

    with caplog.at_level(logging.DEBUG, logger=hass_events.__name__):
        create_hass_event("user_added", data)
        create_hass_event("user_added", data)

    records = [r for r in caplog.records if r.name == hass_events.__name__]
    assert len(records) == 1
    assert getattr(records[0], "key", None) == "secret_key"
    assert getattr(records[0], "payload", None) == "UserAddedPayload"
    assert "secret-value" not in caplog.text
