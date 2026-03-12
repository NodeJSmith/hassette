"""Invocation record dataclass for tracking handler executions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class HandlerInvocationRecord:
    """Record of a single handler invocation for metrics and audit tracking."""

    listener_id: int
    """FK to the listener that was invoked."""

    session_id: int
    """Session during which the invocation occurred."""

    execution_start_ts: float
    """Unix timestamp (epoch seconds) when execution began."""

    duration_ms: float
    """Execution duration in milliseconds."""

    status: str
    """Outcome: 'success', 'error', or 'cancelled'."""

    error_type: str | None
    """Exception class name if status is 'error', otherwise None."""

    error_message: str | None
    """Exception message if status is 'error', otherwise None."""

    error_traceback: str | None
    """Full traceback string if status is 'error', otherwise None."""
