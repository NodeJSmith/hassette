"""Invocation record dataclass for tracking handler executions."""

from dataclasses import dataclass

from hassette.types.types import SourceTier


@dataclass(frozen=True)
class HandlerInvocationRecord:
    """Record of a single handler invocation for metrics and audit tracking."""

    listener_id: int | None
    """FK to the listener that was invoked. None for framework-internal handlers."""

    session_id: int
    """Session during which the invocation occurred."""

    execution_start_ts: float
    """Unix timestamp (epoch seconds) when execution began."""

    duration_ms: float
    """Execution duration in milliseconds."""

    status: str
    """Outcome: 'success', 'error', or 'cancelled'."""

    source_tier: SourceTier = "app"
    """Whether this invocation originates from a user app or the framework itself."""

    is_di_failure: bool = False
    """True when the invocation failed due to a DependencyError (or subclass)."""

    error_type: str | None = None
    """Exception class name if status is 'error', otherwise None."""

    error_message: str | None = None
    """Exception message if status is 'error', otherwise None."""

    error_traceback: str | None = None
    """Full traceback string if status is 'error', otherwise None."""
