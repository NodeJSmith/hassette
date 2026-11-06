"""Home Assistant state adapters that ``BusService`` injects into the bus kernel's ``DurationHoldManager``.

They read HA state dicts and build HA state-change events, so the bus kernel stays free of HA event type imports.
"""

from typing import TYPE_CHECKING

import hassette.utils.date_utils as _date_utils
from hassette.bus.listeners import EntityWatch
from hassette.events import AnyEvent, HassPayload
from hassette.events.base import HassContext
from hassette.events.hass.hass import RawStateChangeEvent, RawStateChangePayload
from hassette.types.enums import Topic

if TYPE_CHECKING:
    from hassette.events.hass.raw import HassStateDict

HASS_STATE_CHANGED_EVENT_TYPE = "state_changed"
"""Home Assistant's ``event_type`` for a state change."""


def make_synthetic_state_event(entity_id: str, current_state: "HassStateDict") -> RawStateChangeEvent:
    """Build a synthetic RawStateChangeEvent with old_state=None from the cached state.

    Carries the cached state's real context (the change that last set it) and the same base topic
    a real state_changed event has, so nothing reading the event records a fabricated context id or
    a second topic shape. Callers that need to label the run synthetic do so on the command
    (``InvokeHandler.is_synthetic``). Injected into the bus kernel so it stays free of HA event type
    imports.
    """
    context = current_state["context"]
    return RawStateChangeEvent(
        topic=Topic.HASS_EVENT_STATE_CHANGED,
        payload=HassPayload(
            event_type=HASS_STATE_CHANGED_EVENT_TYPE,
            data=RawStateChangePayload(
                entity_id=entity_id,
                old_state=None,
                new_state=current_state,
            ),
            # The run's record is labelled HASSETTE_SYNTHETIC from InvokeHandler.is_synthetic (D7 of
            # design/specs/147-execution-trigger-detail), not from this payload.
            origin="LOCAL",
            time_fired=_date_utils.now(),
            context=HassContext(id=context["id"], parent_id=context.get("parent_id"), user_id=context.get("user_id")),
        ),
    )


def compute_elapsed(current_state: "HassStateDict", entity_watch: EntityWatch) -> float:
    """Compute how long an entity has been in its current state.

    Reads the HA-specific ``last_changed`` field from the state dict. Injected
    into the bus kernel so it stays free of HA event type imports.

    For attribute listeners, returns 0.0 (elapsed time is not tracked the same way).
    Returns a value clamped to [0.0, entity_watch.duration].
    """
    duration = entity_watch.duration
    if duration is None:
        return 0.0

    if entity_watch.attribute is not None:
        return 0.0

    last_changed_raw = current_state.get("last_changed")
    if not isinstance(last_changed_raw, str):
        return 0.0

    last_changed = _date_utils.convert_datetime_str_to_tz(last_changed_raw)
    now_dt = _date_utils.now()
    raw_elapsed = (now_dt - last_changed).total("seconds")
    return max(0.0, min(raw_elapsed, duration))


def strip_old_state(event: AnyEvent) -> AnyEvent:
    """Strip old_state from a RawStateChangeEvent for cancel-predicate evaluation.

    For ``RawStateChangeEvent`` with a non-None ``old_state``, returns a copy with
    ``old_state=None`` so that transition predicates (``StateFrom``, ``StateDidChange``)
    do not falsely cancel a duration timer. For all other events, returns the event
    unchanged.
    """
    if isinstance(event, RawStateChangeEvent) and event.payload.data.old_state is not None:
        return RawStateChangeEvent(
            topic=event.topic,
            payload=HassPayload(
                event_type=event.payload.event_type,
                data=RawStateChangePayload(
                    entity_id=event.payload.data.entity_id,
                    old_state=None,
                    new_state=event.payload.data.new_state,
                ),
                origin=event.payload.origin,
                time_fired=event.payload.time_fired,
                context=event.payload.context,
            ),
        )
    return event
