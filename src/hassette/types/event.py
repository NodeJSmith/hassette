import typing
from typing import Any, TypeVar

if typing.TYPE_CHECKING:
    from hassette.events import Event


EventT = TypeVar("EventT", bound="Event[Any]", contravariant=True)
"""Represents a specific event type, e.g., StateChangeEvent, ServiceCallEvent, etc."""
