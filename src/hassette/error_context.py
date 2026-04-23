"""Base error context for bus and scheduler error handlers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorContext:
    """Shared base for error contexts passed to user-registered error handlers.

    Subclassed by :class:`~hassette.bus.error_context.BusErrorContext` and
    :class:`~hassette.scheduler.error_context.SchedulerErrorContext` with
    domain-specific fields.

    Attributes:
        exception: The exception that was raised. Retains its ``__traceback__``
            chain — use ``traceback`` (the string field) for display. The live
            traceback pins originating stack frame locals until this context is
            garbage-collected (bounded by ``error_handler_timeout_seconds``).
        traceback: Formatted traceback string.
    """

    exception: BaseException
    traceback: str

    @property
    def log_label(self) -> str:
        """One-line label identifying the source of the error, used in log messages."""
        raise NotImplementedError
