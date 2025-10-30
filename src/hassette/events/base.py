import itertools
from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar

from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

HASSETTE_EVENT_ID_SEQ = itertools.count(1)


P = TypeVar("P", "HassPayload[Any]", "HassettePayload[Any]", covariant=True)
"""Represents the payload type for an event, either HassPayload or HassettePayload."""

EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)
"""Represents a specific event type, e.g., StateChangeEvent, ServiceCallEvent, etc."""

HassT = TypeVar("HassT", covariant=True)
"""Represents the data payload type for Home Assistant events."""

HassetteT = TypeVar("HassetteT", covariant=True)
"""Represents the data payload type for Hassette events."""


def next_id() -> int:
    return next(HASSETTE_EVENT_ID_SEQ)


@dataclass(slots=True, frozen=True)
class HassContext:
    """Structure for the context of a Home Assistant event."""

    id: str
    parent_id: str | None
    user_id: str | None


@dataclass(slots=True, frozen=True)
class HassPayload(Generic[HassT]):
    """Base class for Home Assistant event payloads."""

    event_type: str
    """Type of the event, e.g., 'state_changed', 'call_service', etc."""

    data: HassT
    """The actual event data from Home Assistant."""

    origin: Literal["LOCAL", "REMOTE"]
    """Origin of the event, either 'LOCAL' or 'REMOTE'."""

    time_fired: ZonedDateTime
    """The time the event was fired."""

    context: HassContext
    """The context of the event."""

    def __post_init__(self):
        if isinstance(self.time_fired, str):
            object.__setattr__(self, "time_fired", convert_datetime_str_to_system_tz(self.time_fired))

    @property
    def entity_id(self) -> str | None:
        """Return the entity_id if present in the data."""
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

    @property
    def event_id(self) -> str:
        """The unique identifier for the event."""
        return self.context.id


@dataclass(slots=True, frozen=True)
class HassettePayload(Generic[HassetteT]):
    """Base class for Hassette event payloads."""

    event_type: str
    """Type of the event, e.g., 'service_status', 'websocket', etc."""

    event_id: int = field(default_factory=next_id, init=False)
    """A unique identifier for the event instance."""

    data: HassetteT
    """The actual event data from Hassette."""


@dataclass(slots=True, frozen=True)
class Event(Generic[P]):
    """Base class for all events, only contains topic and payload.

    Payload will be a HassPayload or a HassettePayload depending on the event source."""

    topic: str
    """The topic of the event, used with the Bus to subscribe to specific event types."""

    payload: P
    """The payload of the event, containing the actual event data from HA or Hassette."""
