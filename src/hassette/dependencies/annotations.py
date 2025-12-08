# ruff: noqa: UP040

# disabling UP040 - the TypeAlias definitions here are useful because we can use StateT
# to provide better type hints in handlers that use these dependencies.

# the new `type` doesn't work quite as well for this purpose

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAlias, TypeVar

from hassette.bus import accessors as A
from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.context import get_state_registry, get_type_registry
from hassette.events import CallServiceEvent, Event, HassContext
from hassette.exceptions import DependencyResolutionError, DomainNotFoundError, InvalidEntityIdError
from hassette.models.states import BaseState, StateT
from hassette.core.state_registry import convert_state_dict_to_model

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
            raise DependencyResolutionError(f"Required dependency returned {type(result).__name__}, expected a value")

        # Check if the result is a tuple containing None or MISSING_VALUE
        if isinstance(result, tuple) and any(r is None or r is MISSING_VALUE for r in result):
            raise DependencyResolutionError("Required dependency returned tuple with None or MISSING_VALUE")

        return result

    return wrapper


def convert_state_dict_to_model_inferred(value: Any) -> BaseState:
    """Convert a raw state dict to a typed state model, inferring the model class from the domain.

    This converter uses the StateRegistry to determine the appropriate model class based on
    the domain in the state dict, then performs the conversion.

    Args:
        value: The raw state dict from Home Assistant

    Returns:
        The typed state model instance

    Raises:
        DependencyResolutionError: If conversion fails or no model found for domain
    """
    registry = get_state_registry()
    converted = registry.try_convert_state(value)
    if converted is None:
        raise DependencyResolutionError(f"Cannot infer model for state dict: {type(value).__name__}")

    return converted


def convert_state_value_via_registry(value: Any, to_type: type) -> Any:
    """Convert a raw state value to a specific Python type using the TypeRegistry.

    This converter is used by state value extractors (StateValueNew, StateValueOld) to transform
    raw Home Assistant state values (like "on", "23.5", timestamps) into properly typed Python
    values using registered conversion functions.

    Args:
        value: The raw state value from Home Assistant
        to_type: The target Python type (e.g., bool, float, ZonedDateTime)

    Returns:
        The converted value in the target type

    Raises:
        TypeError: If no conversion is registered for the value type -> target type
    """
    return get_type_registry().convert(value, to_type)


def identity(x: Any) -> Any:
    """Identity function - returns the input as-is.

    Used when a parameter needs the full event object without transformation.
    """
    return x


def _get_state_value_extractor(name: Literal["new_state", "old_state"]) -> Callable[["RawStateChangeEvent"], Any]:
    """Create an extractor function for state values from old or new state.

    Args:
        name: Which state to extract from ("new_state" or "old_state")

    Returns:
        An extractor function that retrieves the state value from the specified state
    """

    def _state_value_extractor(event: "RawStateChangeEvent") -> Any:
        data = event.payload.data
        state_dict = getattr(data, name)
        if state_dict is None:
            return MISSING_VALUE

        entity_id = state_dict.get("entity_id")
        domain = entity_id.split(".")[0] if entity_id and "." in entity_id else None

        if domain is None:
            raise InvalidEntityIdError(entity_id)

        state_value_type = get_state_registry().get_value_type_for_domain(domain)
        if state_value_type is None:
            raise DomainNotFoundError(domain)

        return state_value_type.from_raw(state_dict.get("state"))

    return _state_value_extractor


# ======================================================================================
# State Object Extractors
# ======================================================================================
# These annotations extract full state objects (dicts) from events and convert them
# to typed Pydantic models using the StateRegistry.

# Extractor: get_state_object_new() -> HassStateDict
# Converter: convert_state_dict_to_model() -> StateT (e.g., LightState)
# Returns: Typed state model, raises if None/MISSING_VALUE
StateNew: TypeAlias = Annotated[
    StateT,
    AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_new), convert_state_dict_to_model),
]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

# Extractor: get_state_object_new() -> HassStateDict | None
# Converter: convert_state_dict_to_model() -> StateT (e.g., LightState)
# Returns: Typed state model or None
MaybeStateNew: TypeAlias = Annotated[
    StateT | None,
    AnnotationDetails["RawStateChangeEvent"](A.get_state_object_new, convert_state_dict_to_model),
]
"""Extract the new state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(new_state: D.MaybeStateNew[states.LightState]):
    if new_state:
        brightness = new_state.attributes.brightness
```
"""

# Extractor: get_state_object_old() -> HassStateDict
# Converter: convert_state_dict_to_model() -> StateT (e.g., LightState)
# Returns: Typed state model, raises if None/MISSING_VALUE
StateOld: TypeAlias = Annotated[
    StateT,
    AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old), convert_state_dict_to_model),
]
"""Extract the old state object from a StateChangeEvent.

Example:
```python
async def handler(old_state: D.StateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""

# Extractor: get_state_object_old() -> HassStateDict | None
# Converter: convert_state_dict_to_model() -> StateT (e.g., LightState)
# Returns: Typed state model or None
MaybeStateOld: TypeAlias = Annotated[
    StateT | None,
    AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old, convert_state_dict_to_model),
]
"""Extract the old state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
```
"""


# ======================================================================================
# State Value Extractors
# ======================================================================================
# These annotations extract the raw state value ("on", 23.5, etc.) and convert it
# to a specific Python type using the TypeRegistry.

# See more: https://github.com/pydantic/pydantic/issues/8202#issuecomment-2453578622

# Extractor: _get_state_value_extractor("new_state") -> raw state value
# Converter: convert_state_value_via_registry() -> StateValueT (bool, float, str, etc.)
# Returns: Typed Python value
type StateValueNew[T] = Annotated[
    T,
    AnnotationDetails["RawStateChangeEvent"](
        ensure_present(_get_state_value_extractor("new_state")), convert_state_value_via_registry
    ),
]
"""Extract the new state value from a StateChangeEvent and convert to target type.

Example:
```python
async def handler(state: D.StateValueNew[bool]):
    if state:
        self.logger.info("Light is on")
```
"""

# Extractor: _get_state_value_extractor("old_state") -> raw state value
# Converter: convert_state_value_via_registry() -> StateValueT (bool, float, str, etc.)
# Returns: Typed Python value
type StateValueOld[T] = Annotated[
    T,
    AnnotationDetails["RawStateChangeEvent"](
        ensure_present(_get_state_value_extractor("old_state")), convert_state_value_via_registry
    ),
]
"""Extract the old state value from a StateChangeEvent and convert to target type.

Example:
```python
async def handler(old_state: D.StateValueOld[bool]):
    if old_state:
        self.logger.info("Light was on")
```
"""

# Extractor: _get_state_value_extractor("new_state") -> raw state value
# Converter: convert_state_value_via_registry() -> StateValueT (bool, float, str, etc.)
# Returns: Typed Python value or None
type MaybeStateValueNew[T] = Annotated[
    T | None,
    AnnotationDetails["RawStateChangeEvent"](_get_state_value_extractor("new_state"), convert_state_value_via_registry),
]
"""Extract the new state value from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(state: D.MaybeStateValueNew[bool]):
    if state is not None:
        self.logger.info("Light is on")
```
"""

# Extractor: _get_state_value_extractor("old_state") -> raw state value
# Converter: convert_state_value_via_registry() -> StateValueT (bool, float, str, etc.)
# Returns: Typed Python value or None
type MaybeStateValueOld[T] = Annotated[
    T | None,
    AnnotationDetails["RawStateChangeEvent"](_get_state_value_extractor("old_state"), convert_state_value_via_registry),
]
"""Extract the old state value from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateValueOld[bool]):
    if old_state is not None:
        self.logger.info("Light was on")
```
"""


# ======================================================================================
# Identity & Metadata Extractors
# ======================================================================================
# These annotations extract simple identity and metadata fields from events.
# No converters needed - values are used as-is.

# Extractor: get_entity_id() -> str
# Converter: None
# Returns: Entity ID string, raises if None/MISSING_VALUE
EntityId: TypeAlias = Annotated[str, AnnotationDetails(ensure_present(A.get_entity_id))]
"""Extract the entity_id from a HassEvent.

Returns the entity ID string (e.g., "light.bedroom").

Example:
```python
async def handler(entity_id: D.EntityId):
    self.logger.info("Entity: %s", entity_id)
```
"""

# Extractor: get_entity_id() -> str | FalseySentinel
# Converter: None
# Returns: Entity ID string or MISSING_VALUE
MaybeEntityId: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails(A.get_entity_id)]
"""Extract the entity_id from a HassEvent, returning MISSING_VALUE sentinel if not present."""

# Extractor: get_domain() -> str
# Converter: None
# Returns: Domain string, raises if None/MISSING_VALUE
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

# Extractor: get_domain() -> str | FalseySentinel
# Converter: None
# Returns: Domain string or MISSING_VALUE
MaybeDomain: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails(A.get_domain)]
"""Extract the domain from a HassEvent, returning MISSING_VALUE sentinel if not present."""

# Extractor: get_context() -> HassContext
# Converter: None
# Returns: HassContext object
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


# ======================================================================================
# Service Call Extractors
# ======================================================================================
# These annotations extract data from service call events.

# Extractor: get_service() -> str
# Converter: None
# Returns: Service name string, raises if None/MISSING_VALUE
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

# Extractor: get_service() -> str | FalseySentinel
# Converter: None
# Returns: Service name string or MISSING_VALUE
MaybeService: TypeAlias = Annotated[str | FalseySentinel, AnnotationDetails[CallServiceEvent](A.get_service)]
"""Extract the service name from a CallServiceEvent, returning MISSING_VALUE sentinel if not present."""

# Extractor: get_service_data() -> dict[str, Any]
# Converter: None
# Returns: Service data dict (empty dict if not present)
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


# ======================================================================================
# Attribute Extractors
# ======================================================================================
# These factory functions create extractors for specific state attributes.
# They convert the full state object to access properly typed attributes.


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
