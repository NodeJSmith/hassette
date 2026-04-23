"""Error context dataclass for bus listener failures."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from hassette.error_context import ErrorContext

if TYPE_CHECKING:
    from hassette.events.base import Event


@dataclass(frozen=True)
class BusErrorContext(ErrorContext):
    """Context passed to bus error handlers when a listener raises an exception.

    Attributes:
        exception: The exception that was raised by the listener. Retains its
            ``__traceback__`` chain — use ``traceback`` (the string field) for display.
            The live traceback pins originating stack frame locals until this context
            is garbage-collected (bounded by ``error_handler_timeout_seconds``).
        traceback: Formatted traceback string. Always a non-empty string — the
            design explicitly requires always-populated tracebacks in the user-facing
            context, unlike the framework's own log suppression which may suppress them.
        topic: The topic the listener was registered on.
        listener_name: The name of the listener function that raised the exception.
        event: The event that was being processed when the exception occurred.
    """

    topic: str
    listener_name: str
    event: "Event[Any]"

    @property
    def log_label(self) -> str:
        return f"topic={self.topic}, listener={self.listener_name}"
