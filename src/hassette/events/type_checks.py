import inspect
from typing import Any, get_origin

from hassette.events.base import Event


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass.

    Does NOT handle Union or Optional types. Use explicit Event types instead:
    - ✅ event: Event
    - ✅ event: RawStateChangeEvent
    - ❌ event: Optional[Event]
    - ❌ event: Event | None
    - ❌ event: Union[Event, RawStateChangeEvent]

    Args:
        annotation: The type annotation to check.

    Returns:
        True if annotation is Event or an Event subclass.
    """
    if annotation is inspect.Parameter.empty:
        return False

    # Get the base class for generic types (Event[T] -> Event)
    # For non-generic types, this returns None, so we check annotation directly
    base_type = get_origin(annotation) or annotation

    return inspect.isclass(base_type) and issubclass(base_type, Event)
