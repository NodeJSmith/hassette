from typing import Any, Literal, Required

from typing_extensions import TypedDict

# These represent the structure of the data as it comes from Home Assistant's websocket API, prior to any processing.


class HassContextDict(TypedDict):
    """Structure for the context of a Home Assistant event."""

    id: str
    parent_id: str | None
    user_id: str | None


class HassStateDict(TypedDict, total=False):
    """Structure for the state of an entity.

    This structure is seen both in a state change event or by calling the HA API to get the state of an entity.
    """

    domain: str
    entity_id: Required[str]
    last_changed: str | None
    last_reported: str | None
    last_updated: str | None
    context: Required[HassContextDict]

    state: Required[Any]
    attributes: Required[dict[str, Any]]


class HassEventDict(TypedDict):
    """Structure for a Home Assistant event as sent over the websocket."""

    event_type: str
    data: dict[str, Any] | None
    origin: Literal["LOCAL", "REMOTE"]
    time_fired: str
    context: HassContextDict


class HassEventEnvelopeDict(TypedDict):
    """The websocket message that wraps a Home Assistant event.

    When turned into an Event, only `event` is read; `type` and `id` are discarded.
    """

    event: HassEventDict
    type: Literal["event"]
    id: int  # from the websocket message, not the event's ID
