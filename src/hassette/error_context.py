"""Base error context for bus and scheduler error handlers."""

from dataclasses import dataclass, field


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
        execution_id: UUIDv7 identifying the execution that failed, or None.
    """

    exception: BaseException
    traceback: str
    execution_id: str | None = field(default=None, kw_only=True)

    @property
    def log_label(self) -> str:
        """One-line label identifying the source of the error, used in log messages."""
        base = self.domain_label
        if self.execution_id:
            return f"{base}, exec={self.execution_id}"
        return base

    @property
    def domain_label(self) -> str:
        raise NotImplementedError
