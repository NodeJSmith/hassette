from types import SimpleNamespace
from typing import Any, cast

from hassette.events import CallServiceEvent, RawStateChangeEvent
from hassette.events.hass.hass import RawStateChangePayload


def create_state_change_event(
    *,
    entity_id: str,
    old_value: Any,
    new_value: Any,
    old_attrs: dict[str, Any] | None = None,
    new_attrs: dict[str, Any] | None = None,
    topic: str = "hass.event.state_changed",
) -> Any:
    data = RawStateChangePayload(
        entity_id=entity_id,
        old_state={"state": old_value, "attributes": old_attrs or {}},  # pyright: ignore[reportArgumentType]
        new_state={"state": new_value, "attributes": new_attrs or {}},  # pyright: ignore[reportArgumentType]
    )

    payload = SimpleNamespace(data=data)
    return cast("RawStateChangeEvent", SimpleNamespace(topic=topic, payload=payload))


def create_call_service_event(
    *,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> CallServiceEvent:
    """Create a mock call service event for testing."""
    data = SimpleNamespace(domain=domain, service=service, service_data=service_data or {})
    payload = SimpleNamespace(data=data)
    return cast("CallServiceEvent", SimpleNamespace(topic="hass.event.call_service", payload=payload))
