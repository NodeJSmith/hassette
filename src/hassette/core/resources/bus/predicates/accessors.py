import logging
import typing
from collections.abc import Callable
from typing import Any

from glom import PathAccessError, glom
from typing_extensions import Sentinel

from hassette.const.misc import MISSING_VALUE

if typing.TYPE_CHECKING:
    from hassette import states
    from hassette.events import CallServiceEvent, HassEvent, StateChangeEvent

LOGGER = logging.getLogger(__name__)


def get_path(path: str) -> Callable[..., Any | Sentinel]:
    """Return a callable that extracts a nested value, returning MISSING_VALUE on failure."""

    def _inner(obj):
        try:
            return glom(obj, path)
        except PathAccessError:
            # no logging for regular PathAccessError; just return MISSING_VALUE
            return MISSING_VALUE
        except Exception as e:
            LOGGER.error("Error accessing path %r: %s - %s", path, type(e).__name__, e)
            return MISSING_VALUE

    return _inner


# --------------------------
# Extractors for state/attributes
# --------------------------


def get_state_value_old(event: "StateChangeEvent[states.StateUnion]") -> Any:
    """Get the old state value from a StateChangeEvent, or MISSING_VALUE if `old_state` is `None`."""
    return event.payload.data.old_state_value


def get_state_value_new(event: "StateChangeEvent[states.StateUnion]") -> Any:
    """Get the new state value from a StateChangeEvent, or MISSING_VALUE if `new_state` is `None`."""
    return event.payload.data.new_state_value


def get_state_value_old_new(event: "StateChangeEvent[states.StateUnion]") -> tuple[Any, Any]:
    """Get a tuple of (old_state_value, new_state_value) from a StateChangeEvent."""
    return get_state_value_old(event), get_state_value_new(event)


def get_attr_old(name: str) -> Callable[["StateChangeEvent[states.StateUnion]"], Any]:
    """Get a specific attribute from the old state in a StateChangeEvent."""

    def _inner(event: "StateChangeEvent[states.StateUnion]") -> Any:
        data = event.payload.data
        old_attrs = data.old_state.attributes.model_dump() if data.old_state else {}
        return old_attrs.get(name, MISSING_VALUE)

    return _inner


def get_attr_new(name: str) -> Callable[["StateChangeEvent[states.StateUnion]"], Any]:
    """Get a specific attribute from the new state in a StateChangeEvent."""

    def _inner(event: "StateChangeEvent[states.StateUnion]") -> Any:
        data = event.payload.data
        new_attrs = data.new_state.attributes.model_dump() if data.new_state else {}
        return new_attrs.get(name, MISSING_VALUE)

    return _inner


def get_attr_old_new(name: str) -> Callable[["StateChangeEvent[states.StateUnion]"], tuple[Any, Any]]:
    """Get a specific attribute from the old and new state in a StateChangeEvent."""

    def _inner(event: "StateChangeEvent[states.StateUnion]") -> tuple[Any, Any]:
        old = get_attr_old(name)(event)
        new = get_attr_new(name)(event)
        return (old, new)

    return _inner


# ---------------------------------------------------------------------------
# Extractors for generic events
# ---------------------------------------------------------------------------


def get_domain(event: "HassEvent") -> Any:
    """Get the domain from the event payload."""
    return get_path("payload.data.domain")(event)


def get_entity_id(event: "HassEvent") -> Any:
    """Get the entity_id from the event payload."""
    return get_path("payload.data.entity_id")(event)


# ---------------------------------------------------------------------------
# Service-call accessors
# ---------------------------------------------------------------------------


def get_service_data(event: "CallServiceEvent") -> dict[str, Any] | Sentinel:
    """Return the service_data dict (or empty dict if missing).

    Returns:
        dict[str, Any] | Sentinel: The service_data dict, or MISSING_VALUE if not present.
    """
    result = get_path("payload.data.service_data")(event)

    if result is MISSING_VALUE:
        return MISSING_VALUE

    if typing.TYPE_CHECKING:
        assert not isinstance(result, Sentinel)

    return result


def get_service_data_key(key: str) -> "Callable[[CallServiceEvent], Any]":
    """Return an accessor that extracts a specific key from service_data.

    Examples
    --------
    Basic equality against a literal::

        ValueIs(source=get_service_data_key("entity_id"), condition="light.living_room")

    Callable condition (value must be an int > 200)::

        ValueIs(source=get_service_data_key("brightness"), condition=lambda v: isinstance(v, int) and v > 200)

    """

    def _inner(event: "CallServiceEvent") -> Any:
        service_data = get_service_data(event)
        if service_data is MISSING_VALUE:
            return MISSING_VALUE

        if typing.TYPE_CHECKING:
            assert not isinstance(service_data, Sentinel)

        return service_data.get(key, MISSING_VALUE)

    return _inner
