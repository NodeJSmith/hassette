"""
Accessors are combined with predicates and annotations to easily and cleanly extract values from events. Instead of
writing a lambda like ``lambda e: e.payload.data.old_state_value``, you can use the accessor ``get_state_value_old``
or use ``get_path("payload.data.old_state_value")`` for a more generic solution.

You generally will not need to use these directly - the main bus helpers use them under the hood to provide
the relevant data to predicates. For example, ``on_state_change`` uses ``get_state_value_old`` and
``get_state_value_new`` to provide the old and new state values to predicates like ``StateFrom`` and ``StateTo``.

Examples:
    Extracting a specific key from service_data

    ```python
    from hassette import accessors as A
    from hassette import predicates as P

    value_is = P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")

    self.bus.on_call_service(
        "light.turn_on",
        handler=handler,
        where=value_is,
    )
    ```

    Extracting a nested value using a glom path

    ```python
    from hassette import accessors as A
    from hassette import predicates as P

    value_is = P.ValueIs(
        source=A.get_path("payload.data.new_state.attributes.geolocation.locality"),
        condition="San Francisco",
    )

    self.bus.on_state_change(
        "sensor.my_device_location",
        handler=handler,
        changed_to=value_is,
    )
    ```
"""

import logging
import typing
from collections.abc import Callable
from typing import Any, cast

from glom import PathAccessError, glom

from hassette.const import MISSING_VALUE
from hassette.const.misc import FalseySentinel
from hassette.events import HassStateDict

if typing.TYPE_CHECKING:
    from hassette.events import CallServiceEvent, HassContext, HassEvent, RawStateChangeEvent

LOGGER = logging.getLogger(__name__)


def get_path(path: str) -> Callable[..., Any | FalseySentinel]:
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


def get_state_value_old(event: "RawStateChangeEvent") -> Any | FalseySentinel:
    """Get the old state value from a RawStateChangeEvent, or MISSING_VALUE if `old_state` is `None`."""
    return event.payload.data.old_state_value


def get_state_value_new(event: "RawStateChangeEvent") -> Any | FalseySentinel:
    """Get the new state value from a RawStateChangeEvent, or MISSING_VALUE if `new_state` is `None`."""
    return event.payload.data.new_state_value


def get_state_value_old_new(event: "RawStateChangeEvent") -> tuple[Any, Any]:
    """Get a tuple of (old_state_value, new_state_value) from a RawStateChangeEvent."""
    return get_state_value_old(event), get_state_value_new(event)


def get_state_object_old(event: "RawStateChangeEvent") -> HassStateDict | None:
    """Get the old state object from a RawStateChangeEvent, or None if `old_state` does not exist."""
    return event.payload.data.old_state


def get_state_object_new(event: "RawStateChangeEvent") -> HassStateDict | None:
    """Get the new state object from a RawStateChangeEvent, or None if `new_state` does not exist."""
    return event.payload.data.new_state


def get_state_object_old_new(event: "RawStateChangeEvent") -> tuple[HassStateDict | None, HassStateDict | None]:
    """Get a tuple of (old_state_object, new_state_object) from a RawStateChangeEvent."""
    return get_state_object_old(event), get_state_object_new(event)


def get_attr_old(name: str) -> Callable[["RawStateChangeEvent"], Any]:
    """Get a specific attribute from the old state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        old_attrs: dict[str, Any] = data.old_state.get("attributes", {}) if data.old_state else {}
        return old_attrs.get(name, MISSING_VALUE)

    return _inner


def get_attr_new(name: str) -> Callable[["RawStateChangeEvent"], Any]:
    """Get a specific attribute from the new state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        new_attrs: dict[str, Any] = data.new_state.get("attributes", {}) if data.new_state else {}
        return new_attrs.get(name, MISSING_VALUE)

    return _inner


def get_attr_old_new(name: str) -> Callable[["RawStateChangeEvent"], tuple[Any, Any]]:
    """Get a specific attribute from the old and new state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> tuple[Any, Any]:
        old = get_attr_old(name)(event)
        new = get_attr_new(name)(event)
        return (old, new)

    return _inner


# ---------------------------------------------------------------------------
# Extractors for generic events
# ---------------------------------------------------------------------------


def get_domain(event: "HassEvent") -> str | FalseySentinel:
    """Get the domain from the event payload."""
    from hassette.events import RawStateChangeEvent

    result = cast("str", get_path("payload.data.domain")(event))
    if result is not MISSING_VALUE:
        return result

    if isinstance(event, RawStateChangeEvent):
        return event.payload.domain or MISSING_VALUE

    entity_id = get_entity_id(event)
    if isinstance(entity_id, str):
        return entity_id.split(".")[0]

    return MISSING_VALUE


def get_entity_id(event: "HassEvent") -> str | FalseySentinel:
    """Get the entity_id from the event payload."""
    from hassette.events import CallServiceEvent

    result = cast("str", get_path("payload.data.entity_id")(event))
    if result is not MISSING_VALUE:
        return result

    if isinstance(event, CallServiceEvent):
        return event.payload.data.service_data.get("entity_id", MISSING_VALUE)

    return MISSING_VALUE


def get_context(event: "HassEvent") -> "HassContext":
    """Get the context dict from the event payload."""
    return cast("HassContext", get_path("payload.context")(event))


# ---------------------------------------------------------------------------
# Service-call accessors
# ---------------------------------------------------------------------------


def get_service(event: "CallServiceEvent") -> str | FalseySentinel:
    """Return the service name being called."""
    return get_path("payload.data.service")(event)


def get_service_data(event: "CallServiceEvent") -> dict[str, Any] | FalseySentinel:
    """Return the service_data dict (or empty dict if missing).

    Returns:
        dict[str, Any] | FalseySentinel: The service_data dict, or MISSING_VALUE if not present.
    """
    return get_path("payload.data.service_data")(event)


def get_service_data_key(key: str) -> "Callable[[CallServiceEvent], Any]":
    """Return an accessor that extracts a specific key from service_data.

    Examples
    --------
    Basic equality against a literal

        ValueIs(source=get_service_data_key("entity_id"), condition="light.living_room")

    Callable condition (value must be an int > 200)

        ValueIs(source=get_service_data_key("brightness"), condition=lambda v: isinstance(v, int) and v > 200)

    """

    def _inner(event: "CallServiceEvent") -> Any:
        service_data = get_service_data(event)
        if service_data is MISSING_VALUE:
            return MISSING_VALUE

        if typing.TYPE_CHECKING:
            assert not isinstance(service_data, FalseySentinel)

        return service_data.get(key, MISSING_VALUE)

    return _inner
