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
from hassette import D, states

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
    from hassette import D, states

    async def handle_state_change(new_state: D.StateNew[states.ButtonState]):
        # new_state is automatically extracted and typed as states.ButtonState
        print(new_state.state)
    ```

    Extracting the entity_id from any HassEvent
    ```python
    from hassette import D

    async def handle_event(entity_id: D.EntityId):
        # entity_id is automatically extracted
        print(entity_id)
    ```

    Writing your own dependency
    ```python
    from pathlib import Path

    from typing import Annotated
    from hassette import A

    async def handle_event(
        file_paths: Annotated[frozenset[Path], A.get_path("payload.data.changed_file_paths")],
    ):
        # do something with file_paths
    ```

"""

import typing
from collections.abc import Callable
from typing import Annotated, Any, TypeAlias, TypeVar

from hassette.const.misc import MISSING_VALUE, FalseySentinel
from hassette.di import AnnotationDetails, identity
from hassette.events import Event, HassContext
from hassette.events.hass.hass import TypedStateChangeEvent as ActualTypedStateChangeEvent
from hassette.exceptions import DependencyResolutionError
from hassette.types import StateT

from . import accessors as A

if typing.TYPE_CHECKING:
    from hassette import (
        RawStateChangeEvent,  # noqa: F401  # used as forward ref in AnnotationDetails["RawStateChangeEvent"]
    )

R = TypeVar("R")


def ensure_present(accessor: Callable[[Any], R]) -> Callable[[Any], R]:
    """Wrap an accessor to raise if it returns None or MISSING_VALUE.

    Args:
        accessor: The accessor function to wrap

    Returns:
        Wrapped accessor that validates the return value
    """

    def wrapper(event: Any) -> R:
        result = accessor(event)

        # Check if the result is None or MISSING_VALUE
        if result is None or result is MISSING_VALUE:
            raise DependencyResolutionError(f"Required dependency returned {type(result).__name__}, expected a value")

        return result

    return wrapper


# This annotation converts a RawStateChangeEvent into a TypedStateChangeEvent
# with typed state objects using the StateRegistry.

# Extractor: identity (full event)
# Returns: TypedStateChangeEvent with typed state
TypedStateChangeEvent: TypeAlias = Annotated[
    ActualTypedStateChangeEvent[StateT], AnnotationDetails["RawStateChangeEvent"](identity)
]
"""Convert a RawStateChangeEvent into a TypedStateChangeEvent with typed state objects.

Example:
```python
async def handler(event: D.TypedStateChangeEvent[states.LightState]):
    brightness = event.payload.data.new_state.attributes.brightness
```
"""

StateNew: TypeAlias = Annotated[
    StateT,
    AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_new)),
]
"""Extract the new state object from a StateChangeEvent.

Example:
```python
async def handler(new_state: D.StateNew[states.LightState]):
    brightness = new_state.attributes.brightness
```
"""

MaybeStateNew: TypeAlias = Annotated[
    StateT | None,
    AnnotationDetails["RawStateChangeEvent"](A.get_state_object_new),
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
    StateT,
    AnnotationDetails["RawStateChangeEvent"](ensure_present(A.get_state_object_old)),
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
    StateT | None,
    AnnotationDetails["RawStateChangeEvent"](A.get_state_object_old),
]
"""Extract the old state object from a StateChangeEvent, allowing for None.

Example:
```python
async def handler(old_state: D.MaybeStateOld[states.LightState]):
    if old_state:
        previous_brightness = old_state.attributes.brightness
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

EventDataT = TypeVar("EventDataT")

EventData: TypeAlias = Annotated[
    EventDataT,
    AnnotationDetails(ensure_present(A.get_path("payload.data"))),
]
"""Extract the typed data from a broadcast event's payload.

Use with ``Bus.emit`` to receive the emitted data pre-extracted and typed.

Example:
```python
async def handler(data: D.EventData[MyData]):
    print(data.some_field)
```
"""
