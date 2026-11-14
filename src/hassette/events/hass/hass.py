from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from logging import getLogger
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar

from hassette.const import MISSING_VALUE
from hassette.events.base import AnyEvent, Event, HassContext, HassPayload
from hassette.types import StateT, Topic
from hassette.utils.date_utils import convert_datetime_str_to_tz

from .raw import HassEventEnvelopeDict, HassStateDict

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from hassette.const.misc import FalseySentinel

LOGGER = getLogger(__name__)

HASS_EVENT_TOPIC_PREFIX = "hass.event."
"""Prefix of every Home Assistant event topic; the event type follows it."""

DataclassT = TypeVar("DataclassT", bound="DataclassInstance")

reported_unknown_keys: set[tuple[str, str]] = set()
"""(class name, key) pairs already logged by `construct_ignoring_unknown_keys`.

Process-global on purpose: a new Home Assistant key is reported once per process, not once per event.
"""


@dataclass(slots=True, frozen=True)
class CallServicePayload:
    """Payload for a call_service event in Home Assistant."""

    domain: str
    service: str
    service_data: dict[str, Any] = field(default_factory=dict)
    service_call_id: str | None = None  # documented by Home Assistant, rarely sent


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
    # sent by Home Assistant but missing from https://www.home-assistant.io/docs/configuration/events/#automation_triggered
    source: str | None = None

    item_id: str | None = None
    """The automation's config ID (its `id:` in YAML). Sent by Home Assistant 2026.11 and later."""

    run_id: str | None = None
    """Identifier of this automation run, matching its trace. Sent by Home Assistant 2026.11 and later."""


@dataclass(slots=True, frozen=True)
class ScriptStartedPayload:
    """Payload for a script_started event in Home Assistant."""

    name: str
    entity_id: str

    item_id: str | None = None
    """The script's config ID (its key in YAML). Sent by Home Assistant 2026.11 and later."""

    run_id: str | None = None
    """Identifier of this script run, matching its trace. Sent by Home Assistant 2026.11 and later."""


@dataclass(slots=True, frozen=True)
class RawStateChangePayload:
    """Payload for a state_changed event in Home Assistant."""

    entity_id: str
    """The entity ID of the entity that changed state."""

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


class TypedStateChangeEvent(Event[HassPayload[TypedStateChangePayload[StateT]]]):
    """Event representing a state change in Home Assistant, with typed state data.

    Handlers receive it through the ``D.TypedStateChangeEvent[T]`` dependency annotation, which converts
    the raw event's state dicts into ``T`` instances. Import this class to name or ``isinstance``-check
    the event that annotation produces.
    """


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


HassEvent: TypeAlias = Event[HassPayload[Any]]
"""Alias for Home Assistant events."""


HASS_EVENT_TYPES: "dict[str, tuple[Topic, type[HassEvent], type[DataclassInstance]]]" = {
    "state_changed": (Topic.HASS_EVENT_STATE_CHANGED, RawStateChangeEvent, RawStateChangePayload),
    "call_service": (Topic.HASS_EVENT_CALL_SERVICE, CallServiceEvent, CallServicePayload),
    "component_loaded": (Topic.HASS_EVENT_COMPONENT_LOADED, ComponentLoadedEvent, ComponentLoadedPayload),
    "service_registered": (Topic.HASS_EVENT_SERVICE_REGISTERED, ServiceRegisteredEvent, ServiceRegisteredPayload),
    "service_removed": (Topic.HASS_EVENT_SERVICE_REMOVED, ServiceRemovedEvent, ServiceRemovedPayload),
    "logbook_entry": (Topic.HASS_EVENT_LOGBOOK_ENTRY, LogbookEntryEvent, LogbookEntryPayload),
    "user_added": (Topic.HASS_EVENT_USER_ADDED, UserAddedEvent, UserAddedPayload),
    "user_removed": (Topic.HASS_EVENT_USER_REMOVED, UserRemovedEvent, UserRemovedPayload),
    "automation_triggered": (
        Topic.HASS_EVENT_AUTOMATION_TRIGGERED,
        AutomationTriggeredEvent,
        AutomationTriggeredPayload,
    ),
    "script_started": (Topic.HASS_EVENT_SCRIPT_STARTED, ScriptStartedEvent, ScriptStartedPayload),
}
"""Home Assistant event types with a typed event: event type -> (topic, event class, payload class).

Any other event type becomes a generic `Event` on `HASS_EVENT_TOPIC_PREFIX + event_type` with its raw data.
"""


def construct_ignoring_unknown_keys(cls: type[DataclassT], data: Mapping[str, Any]) -> DataclassT:
    """Construct dataclass `cls` from `data`, ignoring keys `cls` doesn't declare.

    Home Assistant adds keys to event data and contexts between releases. Dropping the ones a payload doesn't
    know keeps a new key from failing every event of that type. Each dropped key name is logged once at debug
    level; values are never logged, since they can carry user data.
    """
    known = {f.name for f in fields(cls)}
    unknown = [key for key in data if key not in known]
    if not unknown:
        return cls(**data)  # common case: skip copying the dict on every event

    for key in unknown:
        if (cls.__name__, key) not in reported_unknown_keys:
            reported_unknown_keys.add((cls.__name__, key))
            LOGGER.debug(
                "Ignoring unknown key %r in %s from Home Assistant",
                key,
                cls.__name__,
                extra={"payload": cls.__name__, "key": key},
            )
    return cls(**{k: v for k, v in data.items() if k in known})


def create_event_from_hass(data: HassEventEnvelopeDict) -> AnyEvent:
    """Create an Event from a dictionary."""
    event = data["event"]
    event_type = event["event_type"]
    if not event_type:
        raise ValueError("Event data must contain 'event_type' key")

    event_data = event.get("data") or {}
    common_fields = {
        "event_type": event_type,
        "origin": event["origin"],
        "context": construct_ignoring_unknown_keys(HassContext, event["context"]),
        "time_fired": convert_datetime_str_to_tz(event["time_fired"]),
    }

    if event_type in HASS_EVENT_TYPES:
        topic, event_cls, payload_cls = HASS_EVENT_TYPES[event_type]
        data_obj = construct_ignoring_unknown_keys(payload_cls, event_data)
        return event_cls(topic=topic, payload=HassPayload(**common_fields, data=data_obj))

    return Event(topic=f"{HASS_EVENT_TOPIC_PREFIX}{event_type}", payload=HassPayload(**common_fields, data=event_data))
