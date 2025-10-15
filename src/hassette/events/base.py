import itertools
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from whenever import SystemDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

P = TypeVar("P", bound="HassPayload | HassettePayload", covariant=True)

HassT = TypeVar("HassT", covariant=True)
HassetteT = TypeVar("HassetteT", covariant=True)


HASSETTE_EVENT_ID_SEQ = itertools.count(1)


def next_id() -> int:
    return next(HASSETTE_EVENT_ID_SEQ)


@dataclass(slots=True, frozen=True)
class Event(Generic[P]):
    """Base class for all events, only contains topic and payload.

    Payload will be a HassPayload or a HassettePayload depending on the event source."""

    topic: str
    """The topic of the event, used with the Bus to subscribe to specific event types."""

    payload: P
    """The payload of the event, containing the actual event data from HA or Hassette."""


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
    time_fired: SystemDateTime
    context: HassContext

    def __post_init__(self):
        if isinstance(self.time_fired, str):
            object.__setattr__(self, "time_fired", convert_datetime_str_to_system_tz(self.time_fired))

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
class HassettePayload(Generic[HassetteT]):
    """Base class for Hassette event payloads."""

    event_type: str
    event_id: int = field(default_factory=next_id, init=False)
    data: HassetteT
