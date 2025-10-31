import itertools
import typing
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from whenever import ZonedDateTime

from hassette.utils.date_utils import convert_datetime_str_to_system_tz

PayloadT = TypeVar("PayloadT", bound="EventPayload")
DataT = TypeVar("DataT")
EventT = TypeVar("EventT", bound="Event", contravariant=True)

HASSETTE_EVENT_ID_SEQ = itertools.count(1)


class Event(Generic[PayloadT]):
    """Base event with strongly typed payload."""

    def __init__(self, topic: str, payload: PayloadT) -> None:
        self.topic = topic
        self.payload = payload


class EventPayload(Generic[DataT]):
    """Base payload with typed data."""

    event_type: str
    """Type of the event."""

    data: DataT
    """The actual event data."""

    def __init__(self, event_type: str, data: DataT) -> None:
        self.event_type = event_type
        self.data = data


@dataclass(frozen=True, slots=True)
class HassContext:
    """Structure for the context of a Home Assistant event."""

    id: str
    parent_id: str | None
    user_id: str | None


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

    def __init__(
        self, event_type: str, data: DataT, origin: Literal["LOCAL", "REMOTE"], time_fired: str, context: HassContext
    ) -> None:
        super().__init__(event_type, data)
        self.origin = origin

        time_fired_dt = convert_datetime_str_to_system_tz(time_fired)
        if typing.TYPE_CHECKING:
            assert time_fired_dt is not None
        self.time_fired = time_fired_dt
        self.context = context

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


class HassettePayload(EventPayload[DataT]):
    """Hassette event payload with additional metadata."""

    def __init__(self, event_type: str, data: DataT) -> None:
        super().__init__(event_type, data)
        self.event_id = next(HASSETTE_EVENT_ID_SEQ)
