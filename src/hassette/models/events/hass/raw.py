from typing import Any, Literal, Required, TypedDict

# These represent the structure of the data as it comes from Home Assistant's websocket API, prior to any processing.


class HassContextDict(TypedDict):
    """Structure for the context of a state change event."""

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
    """Structure for the state change event data."""

    event_type: str
    data: dict[str, Any] | None
    origin: Literal["LOCAL", "REMOTE"]
    time_fired: str
    context: HassContextDict


class HassEventEnvelopeDict(TypedDict):
    """The structure of what comes from Home Assistant's websocket API for state change events.

    When turned into an Event, the `event` attribute is popped and used to create the event,
    with `type` and `id` being discarded.
    """

    event: HassEventDict
    type: Literal["event"]
    id: int  # from the websocket message, not the event's ID
