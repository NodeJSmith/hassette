import logging
import typing
from dataclasses import asdict, dataclass, field
from typing import Any, Generic, Literal, TypeAlias

from hassette.const import MISSING_VALUE
from hassette.events.base import Event, HassPayload
from hassette.models.states import StateT
from hassette.types import Topic

from .raw import HassEventEnvelopeDict, HassStateDict

if typing.TYPE_CHECKING:
    from hassette.const.misc import FalseySentinel


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class CallServicePayload:
    """Payload for a call_service event in Home Assistant."""

    domain: str
    service: str
    service_data: dict[str, Any] = field(default_factory=dict)
    service_call_id: str | None = None  # have never seen this but the docs say it exists


@dataclass(slots=True, frozen=True)
class ComponentLoadedPayload:
    """Payload for a component_loaded event in Home Assistant."""

    component: str


@dataclass(slots=True, frozen=True)
class ServiceRegisteredPayload:
    """Payload for a service_registered event in Home Assistant."""

    domain: str
    service: str


@dataclass(slots=True, frozen=True)
class ServiceRemovedPayload:
    """Payload for a service_removed event in Home Assistant."""

    domain: str
    service: str


@dataclass(slots=True, frozen=True)
class LogbookEntryPayload:
    """Payload for a logbook_entry event in Home Assistant."""

    name: str
    message: str
    domain: str | None = None
    entity_id: str | None = None


@dataclass(slots=True, frozen=True)
class UserAddedPayload:
    """Payload for a user_added event in Home Assistant."""

    user_id: str


@dataclass(slots=True, frozen=True)
class UserRemovedPayload:
    """Payload for a user_removed event in Home Assistant."""

    user_id: str


@dataclass(slots=True, frozen=True)
class AutomationTriggeredPayload:
    """Payload for an automation_triggered event in Home Assistant."""

    name: str
    entity_id: str
    source: str  # this one isn't on the docs page but is included apparently
    # https://www.home-assistant.io/docs/configuration/events/#automation_triggered


@dataclass(slots=True, frozen=True)
class ScriptStartedPayload:
    """Payload for a script_started event in Home Assistant."""

    name: str
    entity_id: str


@dataclass(slots=True, frozen=True)
class EntityRegistryUpdatedPayload:
    """Payload for an entity_registry_updated event in Home Assistant."""

    action: Literal["create", "update", "remove"]
    entity_id: str
    changes: dict[str, Any] | None = None  # Required with action == "update"
    old_entity_id: str | None = None  # Present when action="update" and entity_id changed


@dataclass(slots=True, frozen=True)
class RawStateChangePayload:
    """Payload for a state_changed event in Home Assistant."""

    entity_id: str
    """"The entity ID of the entity that changed state."""

    old_state: HassStateDict | None
    """The previous state of the entity before it changed. Omitted if the state is set for the first time."""

    new_state: HassStateDict | None
    """The new state of the entity. Omitted if the state has been removed."""

    @property
    def state_value_has_changed(self) -> bool:
        """Check if the state value has changed between old and new states.

        Appropriately handles cases where either state may be None.

        Returns:
            True if the state value has changed, False otherwise.
        """
        return self.old_state_value != self.new_state_value

    @property
    def new_state_value(self) -> "Any | FalseySentinel":
        """Return the value of the new state, or MISSING_VALUE if not present."""
        return self.new_state.get("state") if self.new_state is not None else MISSING_VALUE

    @property
    def old_state_value(self) -> "Any | FalseySentinel":
        """Return the value of the old state, or MISSING_VALUE if not present."""
        return self.old_state.get("state") if self.old_state is not None else MISSING_VALUE

    @property
    def has_new_state(self) -> bool:
        """Check if the new state is not None - not a TypeGuard."""
        return self.new_state is not None

    @property
    def has_old_state(self) -> bool:
        """Check if the old state is not None - not a TypeGuard."""
        return self.old_state is not None

    @property
    def domain(self) -> str:
        """Extract the domain from the entity_id."""
        return self.entity_id.split(".", 1)[0]


@dataclass(slots=True, frozen=True)
class TypedStateChangePayload(Generic[StateT]):
    """Payload for a state_changed event in Home Assistant, with typed state data."""

    entity_id: str
    """The entity ID of the entity that changed state."""

    old_state: StateT | None
    """The previous state of the entity before it changed. Omitted if the state is set for the first time."""

    new_state: StateT | None
    """The new state of the entity. Omitted if the state has been removed."""

    @property
    def domain(self) -> str:
        """Extract the domain from the entity_id."""
        return self.entity_id.split(".", 1)[0]


class RawStateChangeEvent(Event[HassPayload[RawStateChangePayload]]):
    """Event representing a state change in Home Assistant, with raw state data."""


class CallServiceEvent(Event[HassPayload[CallServicePayload]]):
    """Event representing a call service in Home Assistant."""


class ComponentLoadedEvent(Event[HassPayload[ComponentLoadedPayload]]):
    """Event representing a component loaded in Home Assistant."""


class ServiceRegisteredEvent(Event[HassPayload[ServiceRegisteredPayload]]):
    """Event representing a service registered in Home Assistant."""


class ServiceRemovedEvent(Event[HassPayload[ServiceRemovedPayload]]):
    """Event representing a service removed in Home Assistant."""


class LogbookEntryEvent(Event[HassPayload[LogbookEntryPayload]]):
    """Event representing a logbook entry in Home Assistant."""


class UserAddedEvent(Event[HassPayload[UserAddedPayload]]):
    """Event representing a user added in Home Assistant."""


class UserRemovedEvent(Event[HassPayload[UserRemovedPayload]]):
    """Event representing a user removed in Home Assistant."""


class AutomationTriggeredEvent(Event[HassPayload[AutomationTriggeredPayload]]):
    """Event representing an automation triggered in Home Assistant."""


class ScriptStartedEvent(Event[HassPayload[ScriptStartedPayload]]):
    """Event representing a script started in Home Assistant."""


def create_event_from_hass(data: HassEventEnvelopeDict):
    """Create an Event from a dictionary."""

    from hassette.events import Event  # avoid circular import

    event = data.get("event", {})
    event_type = event.get("event_type")
    if not event_type:
        raise ValueError("Event data must contain 'event_type' key")

    event_data = event.get("data", {}) or {}
    event_payload = {
        "event_type": event_type,
        "origin": event["origin"],
        "context": event["context"],
        "time_fired": event["time_fired"],
    }

    match event_type:
        case "state_changed":
            return RawStateChangeEvent(
                topic=Topic.HASS_EVENT_STATE_CHANGED,
                payload=HassPayload(**event_payload, data=RawStateChangePayload(**event_data)),
            )

        case "call_service":
            return CallServiceEvent(
                topic=Topic.HASS_EVENT_CALL_SERVICE,
                payload=HassPayload(**event_payload, data=CallServicePayload(**event_data)),
            )
        case "component_loaded":
            return ComponentLoadedEvent(
                topic=Topic.HASS_EVENT_COMPONENT_LOADED,
                payload=HassPayload(**event_payload, data=ComponentLoadedPayload(**event_data)),
            )
        case "service_registered":
            return ServiceRegisteredEvent(
                topic=Topic.HASS_EVENT_SERVICE_REGISTERED,
                payload=HassPayload(**event_payload, data=ServiceRegisteredPayload(**event_data)),
            )
        case "service_removed":
            return ServiceRemovedEvent(
                topic=Topic.HASS_EVENT_SERVICE_REMOVED,
                payload=HassPayload(**event_payload, data=ServiceRemovedPayload(**event_data)),
            )
        case "logbook_entry":
            return LogbookEntryEvent(
                topic=Topic.HASS_EVENT_LOGBOOK_ENTRY,
                payload=HassPayload(**event_payload, data=LogbookEntryPayload(**event_data)),
            )
        case "user_added":
            return UserAddedEvent(
                topic=Topic.HASS_EVENT_USER_ADDED,
                payload=HassPayload(**event_payload, data=UserAddedPayload(**event_data)),
            )
        case "user_removed":
            return UserRemovedEvent(
                topic=Topic.HASS_EVENT_USER_REMOVED,
                payload=HassPayload(**event_payload, data=UserRemovedPayload(**event_data)),
            )
        case "automation_triggered":
            return AutomationTriggeredEvent(
                topic=Topic.HASS_EVENT_AUTOMATION_TRIGGERED,
                payload=HassPayload(**event_payload, data=AutomationTriggeredPayload(**event_data)),
            )
        case "script_started":
            return ScriptStartedEvent(
                topic=Topic.HASS_EVENT_SCRIPT_STARTED,
                payload=HassPayload(**event_payload, data=ScriptStartedPayload(**event_data)),
            )
        case _:
            pass

    # fallback to generic event
    return Event(topic=f"hass.event.{event_type}", payload=HassPayload(**event_payload, data=event_data))


class TypedStateChangeEvent(Event[HassPayload[TypedStateChangePayload[StateT]]]):
    """Event representing a state change in Home Assistant, with typed state data.

    This is not used directly; use the TypedStateChangeEvent annotation in dependencies instead.
    """

    @classmethod
    def create_typed_state_change_event(cls, event: "RawStateChangeEvent", to_type: type):
        from hassette.core.state_registry import convert_state_dict_to_model

        entity_id = event.payload.data.entity_id
        old_state = event.payload.data.old_state
        new_state = event.payload.data.new_state

        if entity_id is None:
            raise ValueError("State change event data must contain 'entity_id' key")

        new_state_obj = convert_state_dict_to_model(new_state, to_type) if new_state is not None else None
        old_state_obj = convert_state_dict_to_model(old_state, to_type) if old_state is not None else None
        curr_payload = {k: v for k, v in asdict(event.payload).items() if k != "data"}
        payload = TypedStateChangePayload[StateT](
            entity_id=entity_id,
            old_state=old_state_obj,  # type: ignore
            new_state=new_state_obj,  # type: ignore
        )

        return TypedStateChangeEvent(topic=event.topic, payload=HassPayload(**curr_payload, data=payload))


HassEvent: TypeAlias = Event[HassPayload[Any]]
"""Alias for Home Assistant events."""
