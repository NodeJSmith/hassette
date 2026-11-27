import inspect
from typing import Any

from hassette.events.base import Event
from hassette.utils.type_utils import is_subclass_of


def is_event_type(annotation: Any) -> bool:
    """Check if annotation is an Event class or subclass.

    Union annotations (including ``Event | None``) are not unwrapped and return False; annotate with a
    concrete Event type.
    """
    if annotation is inspect.Parameter.empty:
        return False

    return is_subclass_of(annotation, Event)
