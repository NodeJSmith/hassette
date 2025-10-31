import itertools
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

PayloadT = TypeVar("PayloadT", bound="EventPayload")
DataT = TypeVar("DataT")
EventT = TypeVar("EventT", bound="Event", contravariant=True)

HASSETTE_EVENT_ID_SEQ = itertools.count(1)


@dataclass(frozen=True, slots=True)
class Event(Generic[PayloadT]):
    """Base event with strongly typed payload."""

    topic: str
    """Topic of the event."""

    payload: PayloadT
    """The event payload."""


@dataclass(frozen=True, slots=True)
class EventPayload(Generic[DataT]):
    """Base payload with typed data."""

    event_type: str
    """Type of the event."""

    data: DataT
    """The actual event data."""


@dataclass(frozen=True, slots=True)
class HassContext:
    """Structure for the context of a Home Assistant event."""

    id: str
    parent_id: str | None
    user_id: str | None


@dataclass(frozen=True, slots=True)
class HassPayload(EventPayload[DataT]):
    """Home Assistant event payload with additional metadata."""

    event_type: str
    """Type of the event, e.g., 'state_changed', 'call_service', etc."""

    data: DataT
    """The actual event data from Home Assistant."""

    origin: Literal["LOCAL", "REMOTE"]
    """Origin of the event, either 'LOCAL' or 'REMOTE'."""

    time_fired: ZonedDateTime
    """The time the event was fired."""

    context: HassContext
    """The context of the event."""

    def __post_init__(self):
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


@dataclass(frozen=True, slots=True)
class HassettePayload(EventPayload[DataT]):
    """Hassette event payload with additional metadata."""

    event_type: str
    """Type of the event, e.g., 'state_changed', 'call_service', etc."""

    data: DataT
    """The actual event data from Home Assistant."""

    event_id: int = field(default_factory=lambda: next(HASSETTE_EVENT_ID_SEQ))
    """The unique identifier for the event."""
