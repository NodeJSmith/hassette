"""Accessors extract values from events for use with predicates and annotations.

Accessors are combined with predicates and annotations to easily and cleanly extract values from events. Instead of
writing a lambda like ``lambda e: e.payload.data.old_state_value``, you can use the accessor ``get_state_value_old``
or use ``get_path("payload.data.old_state_value")`` for a more generic solution.

You generally will not need to use these directly - the main bus helpers use them under the hood to provide
the relevant data to predicates. For example, ``on_state_change`` uses ``get_state_value_old`` and
``get_state_value_new`` to provide the old and new state values to predicates like ``StateFrom`` and ``StateTo``.

Examples:
    Extracting a specific key from service_data

    ```python
    from hassette import A
    from hassette import P

    value_is = P.ValueIs(source=A.get_service_data_key("entity_id"), condition="light.living_room")

    await self.bus.on_call_service(
        "light.turn_on",
        handler=handler,
        where=value_is,
        name="living_room_turn_on",
    )
    ```

    Extracting a nested value using a glom path

    ```python
    from hassette import A
    from hassette import P

    value_is = P.ValueIs(
        source=A.get_path("payload.data.new_state.attributes.geolocation.locality"),
        condition="San Francisco",
    )

    await self.bus.on_state_change(
        "sensor.my_device_location",
        handler=handler,
        changed_to=value_is,
        name="device_location",
    )
    ```
"""

import typing
from collections.abc import Callable, Sequence
from functools import cache
from logging import getLogger
from typing import Any, cast

from glom import PathAccessError, glom

from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.events import CallServiceEvent, RawStateChangeEvent

if typing.TYPE_CHECKING:
    from hassette.events import HassContext, HassEvent, HassStateDict

LOGGER = getLogger(__name__)
DEFAULT_EXCLUDE = ("last_reported", "last_updated", "last_changed", "context")


@cache
def get_path(path: str) -> Callable[..., Any | FalseySentinel]:
    """Return a callable that extracts a nested value, returning MISSING_VALUE on failure.

    The same path returns the same callable, so a predicate built from it compares equal across
    registrations (``if_exists="skip"`` compares predicate sources by identity).
    """

    def _inner(obj: Any) -> Any | FalseySentinel:
        try:
            return glom(obj, path)
        except PathAccessError:
            # no logging for regular PathAccessError; just return MISSING_VALUE
            return MISSING_VALUE
        except Exception as exc:
            LOGGER.error("Error accessing path %r: %s - %s", path, type(exc).__name__, exc)
            return MISSING_VALUE

    return _inner


# Prebuilt extractors for the fixed paths the accessors below read on every event.
DOMAIN_GETTER = get_path("payload.data.domain")
ENTITY_ID_GETTER = get_path("payload.data.entity_id")
CONTEXT_GETTER = get_path("payload.context")
SERVICE_GETTER = get_path("payload.data.service")
SERVICE_DATA_GETTER = get_path("payload.data.service_data")


def attributes_of(state: "HassStateDict | None") -> dict[str, Any]:
    """Return the attributes dict of a state object, or an empty dict if the state is `None`."""
    return state.get("attributes", {}) if state else {}


def get_state_value_old(event: "RawStateChangeEvent") -> Any | FalseySentinel:
    """Get the old state value from a RawStateChangeEvent, or MISSING_VALUE if `old_state` is `None`."""
    return event.payload.data.old_state_value


def get_state_value_new(event: "RawStateChangeEvent") -> Any | FalseySentinel:
    """Get the new state value from a RawStateChangeEvent, or MISSING_VALUE if `new_state` is `None`."""
    return event.payload.data.new_state_value


def get_state_value_old_new(event: "RawStateChangeEvent") -> tuple[Any, Any]:
    """Get a tuple of (old_state_value, new_state_value) from a RawStateChangeEvent."""
    return get_state_value_old(event), get_state_value_new(event)


def get_state_object_old(event: "RawStateChangeEvent") -> "HassStateDict | None":
    """Get the old state object from a RawStateChangeEvent, or None if `old_state` does not exist."""
    return event.payload.data.old_state


def get_state_object_new(event: "RawStateChangeEvent") -> "HassStateDict | None":
    """Get the new state object from a RawStateChangeEvent, or None if `new_state` does not exist."""
    return event.payload.data.new_state


def get_state_object_old_new(event: "RawStateChangeEvent") -> tuple["HassStateDict | None", "HassStateDict | None"]:
    """Get a tuple of (old_state_object, new_state_object) from a RawStateChangeEvent."""
    return get_state_object_old(event), get_state_object_new(event)


def get_attr_old(name: str) -> Callable[["RawStateChangeEvent"], Any]:
    """Get a specific attribute from the old state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> Any:
        return attributes_of(event.payload.data.old_state).get(name, MISSING_VALUE)

    return _inner


def get_attr_new(name: str) -> Callable[["RawStateChangeEvent"], Any]:
    """Get a specific attribute from the new state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> Any:
        return attributes_of(event.payload.data.new_state).get(name, MISSING_VALUE)

    return _inner


def get_attr_old_new(name: str) -> Callable[["RawStateChangeEvent"], tuple[Any, Any]]:
    """Get a specific attribute from the old and new state in a RawStateChangeEvent."""
    old_getter = get_attr_old(name)
    new_getter = get_attr_new(name)

    def _inner(event: "RawStateChangeEvent") -> tuple[Any, Any]:
        return (old_getter(event), new_getter(event))

    return _inner


def get_attrs_new(names: Sequence[str]) -> Callable[["RawStateChangeEvent"], dict[str, Any]]:
    """Get specific attributes from the new state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> dict[str, Any]:
        new_attrs = attributes_of(event.payload.data.new_state)
        return {name: new_attrs.get(name, MISSING_VALUE) for name in names}

    return _inner


def get_attrs_old(names: Sequence[str]) -> Callable[["RawStateChangeEvent"], dict[str, Any]]:
    """Get specific attributes from the old state in a RawStateChangeEvent."""

    def _inner(event: "RawStateChangeEvent") -> dict[str, Any]:
        old_attrs = attributes_of(event.payload.data.old_state)
        return {name: old_attrs.get(name, MISSING_VALUE) for name in names}

    return _inner


def get_attrs_old_new(
    names: Sequence[str],
) -> Callable[["RawStateChangeEvent"], tuple[dict[str, Any], dict[str, Any]]]:
    """Get specific attributes from the old and new state in a RawStateChangeEvent."""
    old_getter = get_attrs_old(names)
    new_getter = get_attrs_new(names)

    def _inner(event: "RawStateChangeEvent") -> tuple[dict[str, Any], dict[str, Any]]:
        return (old_getter(event), new_getter(event))

    return _inner


def get_all_attrs_old(event: "RawStateChangeEvent") -> dict[str, Any] | FalseySentinel:
    """Get all attributes from the old state in a RawStateChangeEvent."""
    data = event.payload.data
    if data.old_state is None:
        return MISSING_VALUE

    return attributes_of(data.old_state)


def get_all_attrs_new(event: "RawStateChangeEvent") -> dict[str, Any] | FalseySentinel:
    """Get all attributes from the new state in a RawStateChangeEvent."""
    data = event.payload.data
    if data.new_state is None:
        return MISSING_VALUE

    return attributes_of(data.new_state)


def get_all_attrs_old_new(
    event: "RawStateChangeEvent",
) -> tuple[dict[str, Any] | FalseySentinel, dict[str, Any] | FalseySentinel]:
    """Get all attributes from the old and new state in a RawStateChangeEvent."""
    return (get_all_attrs_old(event), get_all_attrs_new(event))


def get_domain(event: "HassEvent") -> str | FalseySentinel:
    """Get the domain from the event payload.

    Tries `payload.data.domain` first, then `payload.domain` for a `RawStateChangeEvent` (derived from its entity_id),
    then the prefix of `get_entity_id(event)`, which covers a `CallServiceEvent` whose service_data names an entity.
    """
    domain = DOMAIN_GETTER(event)
    if domain is not MISSING_VALUE:
        return domain

    if isinstance(event, RawStateChangeEvent):
        return event.payload.domain or MISSING_VALUE

    entity_id = get_entity_id(event)
    if isinstance(entity_id, str):
        return entity_id.split(".")[0]

    return MISSING_VALUE


def get_entity_id(event: "HassEvent") -> str | FalseySentinel:
    """Get the entity_id from the event payload.

    Tries `payload.data.entity_id` first, then `service_data["entity_id"]` for a `CallServiceEvent`.
    """
    entity_id = ENTITY_ID_GETTER(event)
    if entity_id is not MISSING_VALUE:
        return entity_id

    if isinstance(event, CallServiceEvent):
        return event.payload.data.service_data.get("entity_id", MISSING_VALUE)

    return MISSING_VALUE


def get_context(event: "HassEvent") -> "HassContext":
    """Get the `HassContext` object (`id`, `parent_id`, `user_id`) from the event payload."""
    return cast("HassContext", CONTEXT_GETTER(event))


def get_all_changes(
    exclude: Sequence[str] = DEFAULT_EXCLUDE,
) -> Callable[["RawStateChangeEvent"], dict[str, Any]]:
    """Get a dict of changed state and attribute values between old and new states.

    Args:
        exclude (Sequence[str], optional): List of attribute names to exclude from the changes. Defaults to fields
            that change every state update (e.g., `last_updated`, `last_changed`, `context`).

    Returns:
        dict[str, Any]: A dict mapping each changed key to an (old_value, new_value) tuple, or to a nested dict of the
            same shape for dict values.

    Example return value:
        ```
        {
            "state": ("on", "off"),
            "attributes": {
                "rgb_color": ([255, 255, 0], [255, 255, 255]),
                "brightness": (200, 255)
            },
        }
        ```
    """

    def _inner(event: "RawStateChangeEvent") -> dict[str, Any]:
        old = cast("dict", event.payload.data.old_state or {})
        new = cast("dict", event.payload.data.new_state or {})
        return _recursive_get_differences(old, new, exclude=exclude)

    return _inner


def _recursive_get_differences(
    old_dict: dict[str, Any], new_dict: dict[str, Any], exclude: Sequence[str]
) -> dict[str, Any]:
    """Simple recursive diff between two dicts, returning a dict of changed keys to (old_value, new_value)."""
    changed_dict = {}
    for key in set(old_dict.keys()).union(new_dict.keys()):
        if key in exclude:
            continue

        old_value = old_dict.get(key, MISSING_VALUE)
        new_value = new_dict.get(key, MISSING_VALUE)

        if isinstance(old_value, dict) and isinstance(new_value, dict):
            changed_dict[key] = _recursive_get_differences(old_value, new_value, exclude=exclude)
        elif old_value != new_value:
            changed_dict[key] = (old_value, new_value)

    return changed_dict


def get_service(event: "CallServiceEvent") -> str | FalseySentinel:
    """Return the service name being called."""
    return SERVICE_GETTER(event)


def get_service_data(event: "CallServiceEvent") -> dict[str, Any] | FalseySentinel:
    """Return the service_data dict, or MISSING_VALUE if missing.

    Returns:
        dict[str, Any] | FalseySentinel: The service_data dict, or MISSING_VALUE if not present.
    """
    return SERVICE_DATA_GETTER(event)


def get_service_data_key(key: str) -> "Callable[[CallServiceEvent], Any]":
    """Return an accessor that extracts a specific key from service_data.

    Examples:
        Basic equality against a literal

        ```python
        ValueIs(source=get_service_data_key("entity_id"), condition="light.living_room")
        ```

        Callable condition (value must be an int > 200)

        ```python
        ValueIs(source=get_service_data_key("brightness"), condition=lambda v: isinstance(v, int) and v > 200)
        ```
    """

    def _inner(event: "CallServiceEvent") -> Any:
        service_data = get_service_data(event)
        if not isinstance(service_data, dict):
            return MISSING_VALUE

        return service_data.get(key, MISSING_VALUE)

    return _inner
