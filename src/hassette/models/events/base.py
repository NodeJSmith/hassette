from dataclasses import dataclass
from typing import Generic, TypeVar

P = TypeVar("P", covariant=True)


@dataclass(slots=True, frozen=True)
class Event(Generic[P]):
    """Base class for all events, only contains type and payload.

    Payload will be a HassPayload or a HassettePayload depending on the event source."""

    topic: str
    """The topic of the event, used with the Bus to subscribe to specific event types."""

    payload: P
    """The payload of the event, containing the actual event data from HA or Hassette."""
