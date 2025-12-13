"""Dependencies are special annotated types that extract data from events.

These are designed to be used in event handlers to automatically extract commonly used
data from events without boilerplate code.

For example, instead of writing:

```python
async def handle_state_change(event: RawStateChangeEvent):
    new_state = event.payload.data.new_state
    # do something with new_state
```

You can use the `NewState` dependency:
```python
from hassette import dependencies as D
from hassette import states

async def handle_state_change(new_state: D.StateNew[states.ButtonState]):
    # do something with new_state
```

Hassette will automatically extract the value from the incoming event, cast it to the correct type,
and pass it to your handler.

If you need to write your own dependencies, you can easily do so by annotating
your parameter(s) with `Annotated` and either using an existing accessor from
[accessors][hassette.event_handling.accessors] or writing your own accessor function.

Examples:
    Extracting the new state object from a RawStateChangeEvent
    ```python
    from hassette import dependencies as D
    from hassette import states

    async def handle_state_change(new_state: D.StateNew[states.ButtonState]):
        # new_state is automatically extracted and typed as states.ButtonState
        print(new_state.state)
    ```

    Extracting the entity_id from any HassEvent
    ```python
    from hassette import dependencies as D

    async def handle_event(entity_id: D.EntityId):
        # entity_id is automatically extracted
        print(entity_id)
    ```

    Writing your own dependency
    ```python
    from pathlib import Path

    from typing import Annotated
    from hassette import accessors as A

    async def handle_event(
        file_path: Annotated[Path, A.get_path("payload.data.changed_file_path")],
    ):
        # do something with file_path
    ```

"""

import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Generic, TypeAlias, TypeVar

from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.core.state_registry import convert_state_dict_to_model
from hassette.events import Event, HassContext
from hassette.events.hass.hass import TypedStateChangeEvent as ActualTypedStateChangeEvent
from hassette.exceptions import DependencyResolutionError
from hassette.models.states import StateT

from . import accessors as A

if typing.TYPE_CHECKING:
    from hassette import RawStateChangeEvent  # noqa: F401

T = TypeVar("T", bound=Event[Any])
R = TypeVar("R")

T_Any = TypeVar("T_Any", bound=Any)


@dataclass(slots=True, frozen=True)
class AnnotationDetails(Generic[T]):
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

        return result

    return wrapper


def identity(x: Any) -> Any:
    """Identity function - returns the input as-is.

    Used when a parameter needs the full event object without transformation.
    """
    return x


# ======================================================================================
# Typed State Change Event
# ======================================================================================
# This annotation converts a RawStateChangeEvent into a TypedStateChangeEvent
# with typed state objects using the StateRegistry.

# Extractor: identity (full event)
# Converter: create_typed_state_change_event() -> _TypedStateChangeEvent[StateT]
# Returns: TypedStateChangeEvent with typed state
TypedStateChangeEvent: TypeAlias = Annotated[
    ActualTypedStateChangeEvent[StateT],
    AnnotationDetails["RawStateChangeEvent"](identity, ActualTypedStateChangeEvent.create_typed_state_change_event),
]
"""Convert a RawStateChangeEvent into a TypedStateChangeEvent with typed state objects.

Example:
```python
async def handler(event: D.TypedStateChangeEvent[states.LightState]):
    brightness = event.payload.data.new_state.attributes.brightness
```
"""


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
# Converter: lambda to create HassContext
# Returns: HassContext object
EventContext: TypeAlias = Annotated[HassContext, AnnotationDetails[Event](A.get_context, lambda x, _: HassContext(**x))]
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
