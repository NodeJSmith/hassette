"""Dependencies are special annotated types that extract data from events.

These are designed to be used in event handlers to automatically extract commonly used
data from events without boilerplate code.

For example, instead of writing:

```python
async def handle_state_change(event: StateChangeEvent):
    new_state = event.payload.data.new_state
    # do something with new_state
```

You can use the `NewState` dependency:
```python
from hassette import depends as D
from hassette import states

async def handle_state_change(new_state: D.NewState[states.ButtonState]):
    # do something with new_state
```

Hassette will automatically extract the value from the incoming event, cast it to the correct type,
and pass it to your handler.

If you need to write your own dependencies, you can easily do so by annotating
your parameter(s) with `Annotated` and either using an existing accessor from
[accessors][hassette.bus.accessors] or writing your own accessor function.

Examples:
    Extracting the new state object from a StateChangeEvent
    ```python
    from hassette import depends as D
    from hassette import states

    async def handle_state_change(new_state: D.NewState[states.ButtonState]):
        # do something with new_state
    ```

    Extracting the entity_id from any HassEvent
    ```python
    from hassette import depends as D

    async def handle_event(entity_id: D.EntityId):
        # do something with entity_id
    ```

    Writing your own dependency
    ```python
    from pathlib import Path

    from typing import Annotated
    from hassette.bus import accessors as A

    async def handle_event(
        file_path: Annotated[Path, A.get_path("payload.data.changed_file_path")],
    ):
        # do something with file_path
    ```

"""

import typing
from collections.abc import Callable
from inspect import Signature, isclass
from typing import Annotated, Any, Generic, TypeVar, cast, get_args, get_origin

from hassette.bus import accessors as A
from hassette.models.states.base import StateT

if typing.TYPE_CHECKING:
    from hassette.events import Event, StateChangeEvent
    from hassette.models import states


def extract_from_signature(signature: Signature):
    """Extract base types from Annotated types in a function signature."""
    param_details: dict[str, tuple[Any, Callable]] = {}
    for param in signature.parameters.values():
        result = get_type_and_extractor(param.annotation)
        if result:
            param_details[param.name] = result
            continue

        if param.annotation is param.empty:
            continue

        if isclass(param.annotation):
            param_details[param.name] = (param.annotation, lambda x: x)
            continue

        origin = get_origin(param.annotation)
        if isclass(origin) and issubclass(origin, Depends):
            param_details[param.name] = (param.annotation, origin())
            continue

        args = get_args(param.annotation)
        if len(args) == 1:
            param_details[param.name] = (args[0], lambda x: x)

    return param_details


def get_type_and_extractor(annotated: Annotated[Any, ...]) -> tuple[Any, Callable] | None:
    """Extract the base type and extractor from an Annotated type."""
    args = typing.get_args(annotated)
    if typing.get_origin(annotated) is Annotated and args:
        return args[0], args[1]
    return None


T = TypeVar("T")


class Depends(Generic[T]):
    """Base class for dependencies."""

    def __call__(self, event: "Event") -> T:
        raise NotImplementedError()


class NewState(Depends[StateT]):
    """Annotated type for extracting the new state object from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> "states.StateT | None":
        return cast("states.StateT | None", A.get_state_object_new(event))


class OldState(Depends[StateT]):
    """Annotated type for extracting the old state object from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> "states.StateT | None":
        return cast("states.StateT | None", A.get_state_object_old(event))


class OldAndNewStates(Depends[StateT]):
    """Annotated type for extracting the old and new state objects from a StateChangeEvent."""

    def __call__(self, event: "StateChangeEvent") -> tuple["states.StateT | None", "states.StateT | None"]:
        return (
            cast("states.StateT | None", A.get_state_object_old(event)),
            cast("states.StateT | None", A.get_state_object_new(event)),
        )


NewStateValue = Annotated[Any, A.get_state_value_new]
"""Annotated type for extracting the new state value from a StateChangeEvent."""

OldStateValue = Annotated[Any, A.get_state_value_old]
"""Annotated type for extracting the old state value from a StateChangeEvent."""

OldAndNewStateValues = Annotated[tuple[Any, Any], A.get_state_value_old_new]
"""Annotated type for extracting the old and new state values from a StateChangeEvent."""


AttrOld = Annotated[Any, A.get_attr_old]
"""Annotated type for extracting a specific attribute from the old state in a StateChangeEvent."""

AttrNew = Annotated[Any, A.get_attr_new]
"""Annotated type for extracting a specific attribute from the new state in a StateChangeEvent."""

AttrOldAndNew = Annotated[tuple[Any, Any], A.get_attr_old_new]
"""Annotated type for extracting a specific attribute from both old and new states in a StateChangeEvent."""

EntityId = Annotated[str, A.get_entity_id]
"""Annotated type for extracting the entity_id from a HassEvent."""

Domain = Annotated[str, A.get_domain]
"""Annotated type for extracting the domain from a HassEvent."""

ServiceData = Annotated[dict[str, Any], A.get_service_data]
"""Annotated type for extracting the service_data from a CallServiceEvent."""

EventContext = Annotated[dict[str, Any], A.get_context]
"""Annotated type for extracting the context dict from a HassEvent."""
