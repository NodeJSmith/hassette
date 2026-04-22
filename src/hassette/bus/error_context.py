"""Error context dataclass for bus listener failures."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hassette.events.base import Event


@dataclass(frozen=True)
class BusErrorContext:
    """Context passed to bus error handlers when a listener raises an exception.

    Attributes:
        exception: The exception that was raised by the listener.
        traceback: Formatted traceback string. Always a non-empty string — the
            design explicitly requires always-populated tracebacks in the user-facing
            context, unlike the framework's own log suppression which may suppress them.
        topic: The topic the listener was registered on.
        listener_name: The name of the listener function that raised the exception.
        event: The event that was being processed when the exception occurred.
    """

    exception: BaseException
    traceback: str
    topic: str
    listener_name: str
    event: "Event[Any]"
