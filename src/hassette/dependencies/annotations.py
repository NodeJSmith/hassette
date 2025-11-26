# ruff: noqa: UP040

# disabling UP040 - the TypeAlias definitions here are useful because we can use StateT and StateValueT
# to provide better type hints in handlers that use these dependencies.

# the new `type` doesn't work quite as well for this purpose

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, TypeAlias, TypeVar

from hassette.bus import accessors as A
from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.events import CallServiceEvent, Event, HassContext, TypedStateChangeEvent
from hassette.exceptions import InvalidDependencyReturnTypeError
from hassette.models.states import BaseState, StateT, StateValueT

if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent


T = TypeVar("T", bound=Event[Any])
R = TypeVar("R")


@dataclass(slots=True, frozen=True)
class AnnotationDetails[T: Event[Any]]:
    """Details about an annotation used for dependency injection."""

    extractor: Callable[[T], Any]
    """Function to extract the dependency from the event."""

    converter: Callable[[Any, type], Any] | None = None
    """Optional converter function to convert the extracted value to the desired type."""

    def __post_init__(self):
        if not callable(self.extractor):
            raise TypeError("extractor must be a callable")

        if self.converter is not None and not callable(self.converter):
            raise TypeError("converter must be a callable if provided")


def ensure_present(accessor: Callable[[T], R]) -> Callable[[T], R]:
    """Wrap an accessor to raise if it returns None or MISSING_VALUE.

    Args:
        accessor: The accessor function to wrap

    Returns:
        Wrapped accessor that validates the return value
    """

    def wrapper(event: T) -> R:
        result = accessor(event)

        # Check if the result is None or MISSING_VALUE
        if result is None or result is MISSING_VALUE:
            raise InvalidDependencyReturnTypeError(type(result))

        # Check if the result is a tuple containing None or MISSING_VALUE
        if isinstance(result, tuple) and any(r is None or r is MISSING_VALUE for r in result):
            raise InvalidDependencyReturnTypeError(type(result))

        return result

    return wrapper


def state_change_event_converter(event: "RawStateChangeEvent", param_type: type[BaseState]) -> TypedStateChangeEvent:
    """Convert the event to the correct type based on the parameter type.

    Args:
        event: The RawStateChangeEvent instance
        param_type: The type annotation of the parameter

    Returns:
        The converted event
    """

    new_value = event.to_typed_event()
    if type(new_value.payload.data.new_state) not in [param_type, None]:
        raise InvalidDependencyReturnTypeError(type(new_value))

    if type(new_value.payload.data.old_state) not in [param_type, None]:
        raise InvalidDependencyReturnTypeError(type(new_value))

    return new_value


def identity(x: Any) -> Any:
    """Identity function - returns the input as-is."""
    return x


StateChangeEvent: TypeAlias = Annotated[StateT, AnnotationDetails(identity, state_change_event_converter)]
"""The StateChangeEvent itself, with old and new state data converted to State objects of StateT type."""


StateNew: TypeAlias = Annotated[
    StateT, AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_new))
]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

MaybeStateNew: TypeAlias = Annotated[StateT | None, AnnotationDetails["RawStateChangeEvent"](A.get_state_object_new)]
"""Extract the new state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(new_state: D.MaybeStateNew[states.LightState]):
    if new_state:
        brightness = new_state.attributes.brightness
```
"""


StateOld: TypeAlias = Annotated[
    StateT, AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old))
]
"""Extract the old state object from a StateChangeEvent.

Example:
```python
async def handler(old_state: D.StateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""

MaybeStateOld: TypeAlias = Annotated[StateT | None, AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old)]
"""Extract the old state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""


StateOldAndNew: TypeAlias = Annotated[
    tuple[StateT, StateT], AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old_new))
]
"""Extract both old and new state objects from a StateChangeEvent.

Example:
```python
async def handler(states: D.StateOldAndNew[states.LightState]):
    old_state, new_state = states
    if old_state:
        brightness_changed = old_state.attributes.brightness != new_state.attributes.brightness
```
"""

MaybeStateOldAndNew: TypeAlias = Annotated[
    tuple[StateT | None, StateT | None], AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old_new)
]
"""Extract both old and new state objects from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(states: D.MaybeStateOldAndNew[states.LightState]):
    old_state, new_state = states
    if old_state:
        brightness_changed = old_state.attributes.brightness != new_state.attributes.brightness
    if new_state:
        current_brightness = new_state.attributes.brightness
```
"""


StateValueNew: TypeAlias = Annotated[StateValueT, AnnotationDetails["RawStateChangeEvent"](A.get_state_value_new)]
"""Extract the new state value from a StateChangeEvent.

The state value is the string representation of the state (e.g., "on", "off", "25.5").

Example:
```python
async def handler(new_value: D.StateValueNew[str]):
    self.logger.info("New state value: %s", new_value)
```
"""


StateValueOld: TypeAlias = Annotated[StateValueT, AnnotationDetails["RawStateChangeEvent"](A.get_state_value_old)]
"""Extract the old state value from a StateChangeEvent.

The state value is the string representation of the state (e.g., "on", "off", "25.5").

Example:
```python
async def handler(old_value: D.StateValueOld[str]):
    if old_value:
        self.logger.info("Previous state value: %s", old_value)
```
"""

StateValueOldAndNew: TypeAlias = Annotated[
    tuple[StateValueT, StateValueT], AnnotationDetails["RawStateChangeEvent"](A.get_state_value_old_new)
]
"""Extract both old and new state values from a StateChangeEvent.

The state values are the string representations of the states (e.g., "on", "off", "25.5").

Example:
```python
async def handler(values: D.StateValueOldAndNew[str]):
    old_value, new_value = values
    if old_value and old_value != new_value:
        self.logger.info("Changed from %s to %s", old_value, new_value)
```
"""

EntityId: TypeAlias = Annotated[str, AnnotationDetails(ensure_present(A.get_entity_id))]
"""Extract the entity_id from a HassEvent.

Returns the entity ID string (e.g., "light.bedroom").

Example:
```python
async def handler(entity_id: D.EntityId):
    self.logger.info("Entity: %s", entity_id)
```
"""

MaybeEntityId: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails(A.get_entity_id)]
"""Extract the entity_id from a HassEvent, returning MISSING_VALUE sentinel if not present."""

Domain: TypeAlias = Annotated[str, AnnotationDetails(ensure_present(A.get_domain))]
"""Extract the domain from a HassEvent.

Returns the domain string (e.g., "light", "sensor") from the event payload or entity_id.

Example:
```python

async def handler(domain: D.Domain):
    if domain == "light":
        self.logger.info("Light entity event")
```
"""

MaybeDomain: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails(A.get_domain)]
"""Extract the domain from a HassEvent, returning MISSING_VALUE sentinel if not present."""

Service: TypeAlias = Annotated[str, AnnotationDetails[CallServiceEvent](ensure_present(A.get_service))]
"""Extract the service name from a CallServiceEvent.

Returns the service name string (e.g., "turn_on", "turn_off").

Example:
```python
async def handler(service: D.Service):
    if service == "turn_on":
        self.logger.info("Light turned on")
```
"""

MaybeService: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails[CallServiceEvent](A.get_service)]
"""Extract the service name from a CallServiceEvent, returning MISSING_VALUE sentinel if not present."""

ServiceData: TypeAlias = Annotated[dict[str, Any], AnnotationDetails[CallServiceEvent](A.get_service_data)]
"""Extract the service_data dictionary from a CallServiceEvent.

Returns the service data dictionary containing parameters passed to the service call.
Returns an empty dict if no service_data is present.

Example:
```python
async def handler(service_data: D.ServiceData):
    brightness = service_data.get("brightness")
    if brightness:
        self.logger.info("Brightness set to %s", brightness)
```
"""

EventContext: TypeAlias = Annotated[HassContext, AnnotationDetails[Event](A.get_context)]
"""Extract the context object from a HassEvent.

Returns the Home Assistant context object containing metadata about the event
origin (user_id, parent_id, etc.).

Example:
```python
async def handler(context: D.EventContext):
    if context.user_id:
        self.logger.info("Triggered by user: %s", context.user_id)
```
"""


def AttrNew(name: str) -> AnnotationDetails["RawStateChangeEvent"]:  # noqa: N802
    """Factory for creating annotated types to extract specific attributes from the new state.

    Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D

    async def handler(
        brightness: Annotated[int | None, D.AttrNew("brightness")],
    ):
        pass
    ```
    """

    def _inner(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        new_attrs: dict[str, Any] = data.new_state.get("attributes", {}) if data.new_state else {}
        return new_attrs.get(name, MISSING_VALUE)

    return AnnotationDetails["RawStateChangeEvent"](_inner)


def AttrOld(name: str) -> AnnotationDetails["RawStateChangeEvent"]:  # noqa: N802
    """Factory for creating annotated types to extract specific attributes from the old state.

    Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D

    async def handler(
        brightness: Annotated[int | None, D.AttrOld("brightness")],
    ):
        pass
    """

    def _inner(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        old_attrs: dict[str, Any] = data.old_state.get("attributes", {}) if data.old_state else {}
        return old_attrs.get(name, MISSING_VALUE)

    return AnnotationDetails["RawStateChangeEvent"](_inner)


def AttrOldAndNew(name: str) -> AnnotationDetails["RawStateChangeEvent"]:  # noqa: N802
    """Factory for creating annotated types to extract specific attributes from both old and new states.

    Usage:
    ```python
    from typing import Annotated
    from hassette import dependencies as D

    async def handler(
        brightness: Annotated[tuple[int | None, int | None], D.AttrOldAndNew("brightness")],
    ):
        pass
    """

    def _inner(event: "RawStateChangeEvent") -> tuple[Any, Any]:
        data = event.payload.data
        old_attrs: dict[str, Any] = data.old_state.get("attributes", {}) if data.old_state else {}
        new_attrs: dict[str, Any] = data.new_state.get("attributes", {}) if data.new_state else {}
        return old_attrs.get(name, MISSING_VALUE), new_attrs.get(name, MISSING_VALUE)

    return AnnotationDetails["RawStateChangeEvent"](_inner)
