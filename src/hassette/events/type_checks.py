import inspect
from typing import Any, get_origin

from hassette.events.base import Event


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass.

    Union annotations (including ``Event | None``) are not unwrapped and return False; annotate with a
    concrete Event type.
    """
    if annotation is inspect.Parameter.empty:
        return False

    # Get the base class for generic types (Event[T] -> Event)
    # For non-generic types, this returns None, so we check annotation directly
    base_type = get_origin(annotation) or annotation

    return inspect.isclass(base_type) and issubclass(base_type, Event)
