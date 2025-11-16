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

import inspect
import typing
from collections.abc import Callable
from inspect import Signature, isclass
from typing import Annotated, Any, Generic, TypeVar, cast, get_args, get_origin

from hassette.bus import accessors as A
from hassette.models.states.base import StateT

if typing.TYPE_CHECKING:
    from hassette.events import Event, StateChangeEvent
    from hassette.models import states


def is_annotated_type(annotation: Any) -> bool:
    """Check if annotation is an Annotated type."""
    return get_origin(annotation) is Annotated


def is_depends_subclass(annotation: Any) -> bool:
    """Check if annotation is a Depends subclass (like NewState[T])."""
    origin = get_origin(annotation)
    return origin is not None and isclass(origin) and issubclass(origin, Depends)


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass."""
    from hassette.events import Event

    if annotation is inspect.Parameter.empty:
        return False

    origin = get_origin(annotation)
    if origin is not None:
        return isclass(origin) and issubclass(origin, Event)

    return isclass(annotation) and issubclass(annotation, Event)


def extract_from_annotated(annotation: Any) -> tuple[Any, Callable] | None:
    """Extract type and extractor from Annotated[Type, extractor].

    Returns:
        Tuple of (type, extractor) if valid Annotated type with callable metadata.
        None otherwise.
    """
    if not is_annotated_type(annotation):
        return None

    args = get_args(annotation)
    if len(args) < 2:
        return None

    base_type, metadata = args[0], args[1]

    # Metadata must be callable (an extractor function)
    if not callable(metadata):
        return None

    return (base_type, metadata)


def extract_from_depends(annotation: Any) -> tuple[Any, Callable] | None:
    """Extract type and extractor from Depends[T] subclasses like NewState[StateT].

    Returns:
        Tuple of (type, extractor_instance) if valid Depends subclass.
        None otherwise.
    """
    if not is_depends_subclass(annotation):
        return None

    origin = get_origin(annotation)
    type_args = get_args(annotation)

    # Get the type parameter if present, otherwise Any
    param_type = type_args[0] if type_args else Any

    # Create instance of the Depends subclass to use as extractor
    extractor = origin()

    return (param_type, extractor)


def extract_from_event_type(annotation: Any) -> tuple[Any, Callable] | None:
    """Handle plain Event types - user wants the full event passed through.

    Returns:
        Tuple of (Event type, identity function) if annotation is Event subclass.
        None otherwise.
    """
    if not is_event_type(annotation):
        return None

    # Identity function - just pass the event through
    return (annotation, lambda e: e)


def has_dependency_injection(signature: Signature) -> bool:
    """Check if a signature uses any dependency injection."""
    for param in signature.parameters.values():
        if param.annotation is inspect.Parameter.empty:
            continue

        if (
            is_annotated_type(param.annotation)
            or is_depends_subclass(param.annotation)
            or is_event_type(param.annotation)
        ):
            return True

    return False


def validate_di_signature(signature: Signature) -> None:
    """Validate that a signature with DI doesn't have incompatible parameter types.

    Raises:
        ValueError: If signature has VAR_POSITIONAL (*args) or POSITIONAL_ONLY (/) parameters.
    """
    if not has_dependency_injection(signature):
        return

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise ValueError(f"Handler with dependency injection cannot have *args parameter: {param.name}")

        if param.kind == inspect.Parameter.POSITIONAL_ONLY:
            raise ValueError(f"Handler with dependency injection cannot have positional-only parameter: {param.name}")


def extract_from_signature(signature: Signature) -> dict[str, tuple[Any, Callable]]:
    """Extract parameter types and extractors from a function signature.

    Returns a dict mapping parameter name to (type, extractor_callable).
    Validates that DI signatures don't have incompatible parameter kinds.

    Raises:
        ValueError: If signature has incompatible parameters with DI.
    """
    # Validate signature first
    validate_di_signature(signature)

    param_details: dict[str, tuple[Any, Callable]] = {}

    for param in signature.parameters.values():
        annotation = param.annotation

        # Skip parameters without annotations
        if annotation is inspect.Parameter.empty:
            continue

        # Try each extraction strategy in order
        result = (
            extract_from_annotated(annotation)
            or extract_from_depends(annotation)
            or extract_from_event_type(annotation)
        )

        if result:
            param_details[param.name] = result

    return param_details


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
