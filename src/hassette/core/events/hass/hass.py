from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, Self, TypeAlias, TypeVar

from whenever import Instant

from hassette.core import topics
from hassette.core.events import Event
from hassette.models.states import StateT, try_convert_state

from .raw import HassEventEnvelopeDict, HassStateDict

HassT = TypeVar("HassT", covariant=True)
MISSING_VALUE = object()  # Used to indicate a missing value in states


@dataclass(slots=True, frozen=True)
class HassContext:
    """Structure for the context of a state change event."""

    id: str
    parent_id: str | None
    user_id: str | None


@dataclass(slots=True, frozen=True)
class HassPayload(Generic[HassT]):
    """Base class for Home Assistant event payloads."""

    event_type: str
    data: HassT
    origin: Literal["LOCAL", "REMOTE"]
    time_fired: Instant
    context: HassContext

    @property
    def entity_id(self) -> str | None:
        """Return the entity ID if present in the data."""
        return getattr(self.data, "entity_id", None)

    @property
    def domain(self) -> str | None:
        """Return the domain if present in the data."""
        if hasattr(self.data, "domain"):
            return getattr(self.data, "domain", None)

        entity_id = self.entity_id
        if entity_id:
            return entity_id.split(".")[0]
        return None

    @property
    def service(self) -> str | None:
        """Return the service if present in the data."""
        return getattr(self.data, "service", None)


@dataclass(slots=True, frozen=True)
class CallServicePayload:
    domain: str
    service: str
    service_data: dict[str, Any] = field(default_factory=dict)
    service_call_id: str | None = None  # have never seen this but the docs say it exists


@dataclass(slots=True, frozen=True)
class ComponentLoadedPayload:
    component: str


@dataclass(slots=True, frozen=True)
class ServiceRegisteredPayload:
    domain: str
    service: str


@dataclass(slots=True, frozen=True)
class ServiceRemovedPayload:
    domain: str
    service: str


@dataclass(slots=True, frozen=True)
class LogbookEntryPayload:
    name: str
    message: str
    domain: str | None = None
    entity_id: str | None = None


@dataclass(slots=True, frozen=True)
class UserAddedPayload:
    user_id: str


@dataclass(slots=True, frozen=True)
class UserRemovedPayload:
    user_id: str


@dataclass(slots=True, frozen=True)
class AutomationTriggeredPayload:
    name: str
    entity_id: str
    source: str  # this one isn't on the docs page but is included apparently
    # https://www.home-assistant.io/docs/configuration/events/#automation_triggered


@dataclass(slots=True, frozen=True)
class ScriptStartedPayload:
    name: str
    entity_id: str


@dataclass(slots=True, frozen=True)
class StateChangePayload(Generic[StateT]):
    entity_id: str
    old_state: None | StateT
    """The previous state of the entity before it changed. Omitted if the state is set for the first time."""

    new_state: None | StateT
    """The new state of the entity. Omitted if the state has been removed."""

    @property
    def state_value_has_changed(self) -> bool:
        """Check if the state value has changed between old and new states.

        Appropriately handles cases where either state may be None.

        Returns:
            bool: True if the state value has changed, False otherwise.
        """
        return self.old_state_value != self.new_state_value

    @property
    def new_state_value(self) -> Any:
        """Return the value of the new state, or MISSING_VALUE if not present."""
        return self.new_state.value if self.new_state is not None else MISSING_VALUE

    @property
    def old_state_value(self) -> Any:
        """Return the value of the old state, or MISSING_VALUE if not present."""
        return self.old_state.value if self.old_state is not None else MISSING_VALUE

    @property
    def has_new_state(self) -> bool:
        """Check if the new state is not None."""
        return self.new_state is not None

    @property
    def has_old_state(self) -> bool:
        """Check if the old state is not None."""
        return self.old_state is not None

    @classmethod
    def create_from_event(
        cls, entity_id: str, old_state: HassStateDict | None = None, new_state: HassStateDict | None = None
    ) -> Self:
        if entity_id is None:
            raise ValueError("State change event data must contain 'entity_id' key")

        # use deepcopy to avoid mutating the original data
        old_state_obj = try_convert_state(deepcopy(old_state)) if old_state else None
        new_state_obj = try_convert_state(deepcopy(new_state)) if new_state else None

        return cls(entity_id=entity_id, old_state=old_state_obj, new_state=new_state_obj)  # pyright: ignore[reportArgumentType]


def create_event_from_hass(
    data: "HassEventEnvelopeDict",
):
    """Create an Event from a dictionary."""

    from hassette.core.events import Event  # avoid circular import

    event = data.get("event", {})
    event_type = event.get("event_type")
    if not event_type:
        raise ValueError("Event data must contain 'event_type' key")

    event_data = event.get("data", {}) or {}
    event_payload = {
        "event_type": event_type,
        "context": event["context"],
        "origin": event["origin"],
        "time_fired": event["time_fired"],
    }

    if event_type == "state_changed":
        return Event(
            topic=topics.HASS_EVENT_STATE_CHANGED,
            payload=HassPayload(**event_payload, data=StateChangePayload.create_from_event(**event_data)),
        )

    match event_type:
        case "call_service":
            payload_cls = CallServicePayload
            topic = topics.HASS_EVENT_CALL_SERVICE
        case "component_loaded":
            payload_cls = ComponentLoadedPayload
            topic = topics.HASS_EVENT_COMPONENT_LOADED
        case "service_registered":
            payload_cls = ServiceRegisteredPayload
            topic = topics.HASS_EVENT_SERVICE_REGISTERED
        case "service_removed":
            payload_cls = ServiceRemovedPayload
            topic = topics.HASS_EVENT_SERVICE_REMOVED
        case "logbook_entry":
            payload_cls = LogbookEntryPayload
            topic = topics.HASS_EVENT_LOGBOOK_ENTRY
        case "user_added":
            payload_cls = UserAddedPayload
            topic = topics.HASS_EVENT_USER_ADDED
        case "user_removed":
            payload_cls = UserRemovedPayload
            topic = topics.HASS_EVENT_USER_REMOVED
        case "automation_triggered":
            payload_cls = AutomationTriggeredPayload
            topic = topics.HASS_EVENT_AUTOMATION_TRIGGERED
        case "script_started":
            payload_cls = ScriptStartedPayload
            topic = topics.HASS_EVENT_SCRIPT_STARTED
        case _:
            payload_cls = dict
            topic = f"hass.event.{event_type}"

    if payload_cls:
        return Event(topic=topic, payload=HassPayload(**event_payload, data=payload_cls(**event_data)))

    raise ValueError(f"Unknown event type: {event_type}")


StateChangeEvent: TypeAlias = Event[HassPayload[StateChangePayload[StateT]]]
CallServiceEvent: TypeAlias = Event[HassPayload[CallServicePayload]]
ComponentLoadedEvent: TypeAlias = Event[HassPayload[ComponentLoadedPayload]]
ServiceRegisteredEvent: TypeAlias = Event[HassPayload[ServiceRegisteredPayload]]
ServiceRemovedEvent: TypeAlias = Event[HassPayload[ServiceRemovedPayload]]
LogbookEntryEvent: TypeAlias = Event[HassPayload[LogbookEntryPayload]]
UserAddedEvent: TypeAlias = Event[HassPayload[UserAddedPayload]]
UserRemovedEvent: TypeAlias = Event[HassPayload[UserRemovedPayload]]
AutomationTriggeredEvent: TypeAlias = Event[HassPayload[AutomationTriggeredPayload]]
ScriptStartedEvent: TypeAlias = Event[HassPayload[ScriptStartedPayload]]

HassEvent: TypeAlias = Event[HassPayload[Any]]
