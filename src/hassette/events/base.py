import typing
import uuid
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from whenever import ZonedDateTime

from hassette.types import PayloadT

if typing.TYPE_CHECKING:
    from hassette.types import Topic

DataT = TypeVar("DataT", covariant=True)
"""Represents the data type within an event payload."""


@dataclass(frozen=True, slots=True)
class EventPayload(Generic[DataT]):
    """Base payload with typed data."""

    data: DataT
    """The actual event data."""

    event_id: str = field(default="", kw_only=True)
    """Unique identifier for this event. Subclasses override with a more specific default."""

    origin: str = field(default="UNKNOWN", kw_only=True)
    """Origin of the event. Subclasses override with a concrete value."""


@dataclass(frozen=True, slots=True)
class HassContext:
    """Structure for the context of a Home Assistant event."""

    id: str
    parent_id: str | None
    user_id: str | None


@dataclass(frozen=True, slots=True, repr=False)
class HassPayload(EventPayload[DataT]):
    """Home Assistant event payload with additional metadata."""

    event_type: str
    """Type of the event, e.g., 'state_changed', 'call_service', etc."""

    data: DataT
    """The actual event data from Home Assistant."""

    origin: Literal["LOCAL", "REMOTE"]  # pyright: ignore[reportGeneralTypeIssues]
    """Origin of the event, either 'LOCAL' or 'REMOTE'."""

    time_fired: ZonedDateTime  # pyright: ignore[reportGeneralTypeIssues]
    """The time the event was fired."""

    context: HassContext  # pyright: ignore[reportGeneralTypeIssues]
    """The context of the event."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", self.context.id)

    @property
    def entity_id(self) -> str | None:
        """Return the entity_id if present in the data."""
        return getattr(self.data, "entity_id", None)

    @property
    def domain(self) -> str | None:
        """Return the domain if present in the data."""
        domain = getattr(self.data, "domain", None)
        if domain is not None:
            return domain

        entity_id = self.entity_id
        if entity_id:
            return entity_id.split(".")[0]
        return None

    @property
    def service(self) -> str | None:
        """Return the service if present in the data."""
        return getattr(self.data, "service", None)

    def __repr__(self) -> str:
        if self.entity_id:
            return f"HassPayload(event_type={self.event_type}, entity_id={self.entity_id}, event_id={self.event_id})"

        return f"HassPayload(event_type={self.event_type}, event_id={self.event_id})"


@dataclass(frozen=True, slots=True, repr=False)
class HassettePayload(EventPayload[DataT]):
    """Hassette event payload with additional metadata."""

    data: DataT
    """The actual event data."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this payload instance (UUID4), generated at construction time.

    The bus shares one payload instance with all matched listeners, so all handlers
    for the same event see the same ``event_id``.
    """

    time_fired: ZonedDateTime = field(default_factory=lambda: ZonedDateTime.now("UTC"))
    """The time the event was fired, defaulting to the current UTC time at construction."""

    origin: str = field(default="HASSETTE", init=False)
    """Origin of the event, always 'HASSETTE' for framework-generated events."""

    def __repr__(self) -> str:
        return f"HassettePayload(event_id={self.event_id}, time_fired={self.time_fired})"


@dataclass(frozen=True, slots=True, repr=False)
class Event(Generic[PayloadT]):
    """Base event with strongly typed payload."""

    topic: "Topic | str"
    """Topic of the event."""

    payload: PayloadT
    """The event payload."""

    def __repr__(self) -> str:
        return f"Event({self.payload})"
