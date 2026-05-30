"""Unified execution record dataclass for tracking handler and job executions."""

from dataclasses import dataclass
from typing import Literal

from hassette.types.types import SourceTier


@dataclass(frozen=True)
class ExecutionRecord:
    """Unified record of a single handler invocation or job execution.

    ``kind`` discriminates between the two execution types.  Handler-only fields
    (``trigger_context_id``, ``trigger_origin``) default to ``None`` for job
    executions.  Job-only fields (``args_json``, ``kwargs_json``) are included
    on both kinds; handlers use the defaults (``'[]'`` / ``'{}'``).
    """

    kind: Literal["handler", "job"]
    """Execution type: 'handler' for bus invocations, 'job' for scheduled-job executions."""

    session_id: int | None
    """Session during which the execution occurred.

    None when enqueued before session creation; injected at drain time.
    """

    execution_start_ts: float
    """Unix timestamp (epoch seconds) when execution began."""

    duration_ms: float
    """Execution duration in milliseconds."""

    status: str
    """Outcome: 'success', 'error', 'cancelled', or 'timed_out'."""

    # --- FK fields: exactly one will be non-None (matches the DB CHECK constraint) ---
    listener_id: int | None = None
    """FK to the listeners table. Set for handler executions; None for job executions."""

    job_id: int | None = None
    """FK to the scheduled_jobs table. Set for job executions; None for handler executions."""

    # --- Ownership / attribution ---
    app_key: str = ""
    """App key that owns this execution. Empty string for framework-internal executions."""

    instance_index: int = 0
    """Instance index within the app."""

    source_tier: SourceTier = "app"
    """Whether this execution originates from a user app or the framework itself."""

    # --- Error details ---
    is_di_failure: bool = False
    """True when the execution failed due to a DependencyError (or subclass)."""

    error_type: str | None = None
    """Exception class name if status is 'error', otherwise None."""

    error_message: str | None = None
    """Exception message if status is 'error', otherwise None."""

    error_traceback: str | None = None
    """Full traceback string if status is 'error', otherwise None."""

    # --- Execution identity ---
    execution_id: str | None = None
    """UUIDv7 string identifying the specific execution instance. None when not populated."""

    # --- Handler-only fields ---
    trigger_context_id: str | None = None
    """event_id from the triggering HA event payload.

    None for job executions and for non-event-triggered or synthetic handler invocations.
    """

    trigger_origin: str | None = None
    """Origin of the triggering event (e.g., 'LOCAL', 'REMOTE', 'HASSETTE', 'HASSETTE_SYNTHETIC').

    None for job executions and when origin is not available.
    """

    # --- New unified-table columns (001.sql) ---
    trigger_mode: str | None = None
    """Trigger mode string (e.g., 'immediate', 'debounced'). None when not set."""

    retry_count: int = 0
    """Number of retry attempts before this execution. 0 for first attempts."""

    attempt_number: int = 1
    """Ordinal attempt number (1-based). 1 for first attempt."""

    args_json: str = "[]"
    """JSON-encoded positional arguments. '[]' for handler executions."""

    kwargs_json: str = "{}"
    """JSON-encoded keyword arguments. '{}' for handler executions."""
