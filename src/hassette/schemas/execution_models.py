"""The latest-error record that the execution telemetry queries read per app."""

from typing import NamedTuple


class AppLastError(NamedTuple):
    """An app's most recent failed execution: its error message, error type, and start timestamp."""

    error_message: str
    error_type: str | None
    timestamp: float
