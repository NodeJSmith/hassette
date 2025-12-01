# ruff: noqa: UP040

# disabling UP040 - the TypeAlias definitions here are useful because we can use StateT and StateValueT
# to provide better type hints in handlers that use these dependencies.

# the new `type` doesn't work quite as well for this purpose

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias, TypeAliasType, TypeVar

from hassette.bus import accessors as A
from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.context import get_state_registry
from hassette.events import CallServiceEvent, Event, HassContext
from hassette.exceptions import InvalidDependencyReturnTypeError
from hassette.models.states import BaseState, StateT
from hassette.types import StateType
from hassette.types.state_value import TYPE_ALIAS_TO_CONVERTER_MAP, TYPE_TO_CONVERTER_MAP

if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent


T = TypeVar("T", bound=Event[Any])
R = TypeVar("R")

T_Any = TypeVar("T_Any", bound=Any)


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


def convert_to_model(value: Any, model: type[BaseState]) -> BaseState:
    """Convert a raw state dict to a typed state model.

    Args:
        value: The raw state dict
        model: The target state model class

    Returns:
        The typed state model instance
    """
    if isinstance(value, model):
        return value

    if not isinstance(value, dict):
        raise InvalidDependencyReturnTypeError(type(value))

    return model.model_validate(value)


def convert_to_model_implicit(value: Any) -> BaseState:
    """Convert a raw state dict to a typed state model, inferring the model from the value.

    Args:
        value: The raw state dict

    Returns:
        The typed state model instance
    """
    registry = get_state_registry()
    converted = registry.try_convert_state(value)
    if converted is None:
        raise InvalidDependencyReturnTypeError(type(value))

    return converted


def identity(x: Any) -> Any:
    """Identity function - returns the input as-is."""
    return x


def _get_state_value_extractor(name: Literal["new_state", "old_state"]) -> Callable[["RawStateChangeEvent"], Any]:
    def _state_value_extractor(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        state_dict = getattr(data, name)
        if state_dict is None:
            return MISSING_VALUE
        return convert_to_model_implicit(state_dict)

    return _state_value_extractor


def _get_converter_fn(
    type_value: type | StateType | TypeAliasType,
) -> Callable[[type | TypeAliasType | StateType], Any]:
    if type_value in TYPE_ALIAS_TO_CONVERTER_MAP:
        return TYPE_ALIAS_TO_CONVERTER_MAP[type_value]
    if type_value in TYPE_TO_CONVERTER_MAP:
        return TYPE_TO_CONVERTER_MAP[type_value]
    raise ValueError(f"Unsupported state value type: {type_value}")


def _state_value_helper(
    name: Literal["new_state", "old_state"], type_value: type | StateType | TypeAliasType
) -> AnnotationDetails["RawStateChangeEvent"]:
    if type_value not in TYPE_ALIAS_TO_CONVERTER_MAP:
        raise ValueError(f"Unsupported state value type: {type_value}")

    extractor = _get_state_value_extractor(name)
    converter_fn = _get_converter_fn(type_value)

    def converter(value: Any, _: type):
        return converter_fn(value.value)

    return AnnotationDetails["RawStateChangeEvent"](extractor, converter)


StateNew: TypeAlias = Annotated[
    StateT, AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_new), convert_to_model)
]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

MaybeStateNew: TypeAlias = Annotated[
    StateT | None, AnnotationDetails["RawStateChangeEvent"](A.get_state_object_new, convert_to_model)
]
"""Extract the new state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(new_state: D.MaybeStateNew[states.LightState]):
    if new_state:
        brightness = new_state.attributes.brightness
```
"""


StateOld: TypeAlias = Annotated[
    StateT, AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old), convert_to_model)
]
"""Extract the old state object from a StateChangeEvent.

Example:
```python
async def handler(old_state: D.StateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""

MaybeStateOld: TypeAlias = Annotated[
    StateT | None, AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old, convert_to_model)
]
"""Extract the old state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""


StateOldAndNew: TypeAlias = Annotated[
    tuple[StateT, StateT],
    AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old_new), convert_to_model),
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
    tuple[StateT | None, StateT | None],
    AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old_new, convert_to_model),
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


def StateValueNew(type_value: type | StateType | TypeAliasType) -> AnnotationDetails["RawStateChangeEvent"]:  # noqa: N802
    """Factory for creating annotated types to extract the new state value as a specific model."""
    return _state_value_helper("new_state", type_value)


def StateValueOld(type_value: type | StateType | TypeAliasType) -> AnnotationDetails["RawStateChangeEvent"]:  # noqa: N802
    """Factory for creating annotated types to extract the old state value as a specific model."""

    return _state_value_helper("old_state", type_value)


def StateValueOldAndNew(  # noqa: N802
    type_value: tuple[type | StateType | TypeAliasType, type | StateType | TypeAliasType],
) -> AnnotationDetails["RawStateChangeEvent"]:
    """Factory for creating annotated types to extract both old and new state values as a specific model."""

    if not isinstance(type_value, tuple) or len(type_value) != 2:
        raise ValueError("type_value must be a tuple of two types for old and new state values.")

    def extractor(event: "RawStateChangeEvent") -> tuple[Any, Any]:
        old_value = _get_state_value_extractor("old_state")(event)
        new_value = _get_state_value_extractor("new_state")(event)
        return old_value, new_value

    converter_fn_old = _get_converter_fn(type_value[0])
    converter_fn_new = _get_converter_fn(type_value[1])

    def converter(value: Any, _: type) -> Any:
        old_converted = converter_fn_old(value[0].value)
        new_converted = converter_fn_new(value[1].value)
        return old_converted, new_converted

    return AnnotationDetails["RawStateChangeEvent"](extractor, converter)


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
        if event.payload.data.new_state is None:
            return MISSING_VALUE

        registry = get_state_registry()
        converted = registry.try_convert_state(event.payload.data.new_state)
        return getattr(converted.attributes, name, MISSING_VALUE)

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
        if event.payload.data.old_state is None:
            return MISSING_VALUE

        registry = get_state_registry()
        converted = registry.try_convert_state(event.payload.data.old_state)
        return getattr(converted.attributes, name, MISSING_VALUE)

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
        # Old attribute
        if event.payload.data.old_state is None:
            old_attr = MISSING_VALUE
        else:
            registry = get_state_registry()
            converted_old = registry.try_convert_state(event.payload.data.old_state)
            old_attr = getattr(converted_old.attributes, name, MISSING_VALUE)

        # New attribute
        if event.payload.data.new_state is None:
            new_attr = MISSING_VALUE
        else:
            registry = get_state_registry()
            converted_new = registry.try_convert_state(event.payload.data.new_state)
            new_attr = getattr(converted_new.attributes, name, MISSING_VALUE)

        return old_attr, new_attr

    return AnnotationDetails["RawStateChangeEvent"](_inner)
