"""Unified execution record dataclass for tracking handler and job executions."""

from dataclasses import dataclass
from typing import Literal

from hassette_wire import ExecutionStatus, SourceTier

SYNTHETIC_ORIGIN = "HASSETTE_SYNTHETIC"
"""trigger_origin value for immediate-fire runs, whose event hassette built from the cached state."""


@dataclass(frozen=True)
class ExecutionRecord:
    """Unified record of a single handler invocation or job execution.

    ``kind`` discriminates between the two execution types.  Handler-only ``trigger_*`` fields
    (everything except ``trigger_mode``) default to ``None`` for job executions.  Job-only fields
    (``args_json``, ``kwargs_json``) are included on both kinds; handlers use the defaults
    (``'[]'`` / ``'{}'``).
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

    status: ExecutionStatus
    """Outcome: `ExecutionStatus.SUCCESS`, `.ERROR`, `.CANCELLED`, `.TIMED_OUT`, or `.SKIPPED`."""

    # FK fields: exactly one will be non-None (matches the DB CHECK constraint)
    listener_id: int | None = None
    """FK to the listeners table. Set for handler executions; None for job executions."""

    job_id: int | None = None
    """FK to the scheduled_jobs table. Set for job executions; None for handler executions."""

    # Ownership / attribution
    app_key: str = ""
    """App key that owns this execution. Empty string for framework-internal executions."""

    source_tier: SourceTier = "app"
    """Whether this execution originates from a user app or the framework itself."""

    # Error details
    is_di_failure: bool = False
    """True when the execution failed due to a DependencyError (or subclass)."""

    thread_leaked: bool = False
    """True when the execution timed out and the worker thread was still alive after the timeout.

    Set only for sync handlers whose worker thread outlived the asyncio timeout.  False for
    async handlers, for executions that never started their worker (not-started timeout), and
    for all non-timed-out executions.  Corresponds to the ``thread_leaked`` column in the
    ``executions`` table (004.sql).

    Subject to a small race window: if the worker finishes between the timeout cancellation and the
    liveness check, this field reads False even though the thread outlived the asyncio deadline.
    This is a false-negative (undercounting), not a false-positive. Treat as a lower bound.
    """

    error_type: str | None = None
    """Exception class name if status is `ExecutionStatus.ERROR`, otherwise None."""

    error_message: str | None = None
    """Exception message if status is `ExecutionStatus.ERROR`, otherwise None."""

    error_traceback: str | None = None
    """Full traceback string if status is `ExecutionStatus.ERROR`, otherwise None."""

    # Execution identity
    execution_id: str | None = None
    """UUIDv7 string identifying the specific execution instance. None when not populated."""

    # Handler-only fields
    trigger_context_id: str | None = None
    """event_id of the triggering event: the HA context id, or a Hassette event's uuid4.

    None for job executions. An immediate-fire run records the context of the change that set the
    cached state it was built from.
    """

    trigger_origin: str | None = None
    """Origin of the triggering event (e.g., 'LOCAL', 'REMOTE', 'HASSETTE', 'HASSETTE_SYNTHETIC').

    None for job executions and when origin is not available.
    """

    trigger_parent_id: str | None = None
    """``context.parent_id`` of the triggering HA event. None for Hassette events and job executions."""

    trigger_topic: str | None = None
    """The triggering event's own topic (e.g. ``hass.event.state_changed``), not the listener's route."""

    trigger_entity_id: str | None = None
    """Entity the triggering event is about. None for events without one (e.g. ``call_service``)."""

    trigger_old_value: str | None = None
    """Tracked value before the change: the state, or the listener's tracked attribute.

    A display string capped at ``TRIGGER_VALUE_MAX_CHARS`` (see ``execution_record_builder``).
    None when the old state is missing or the event is not a state change.
    """

    trigger_new_value: str | None = None
    """Tracked value after the change; same rules as ``trigger_old_value``."""

    # Reserved unified-table columns (001.sql)
    # These columns exist in the schema and round-trip through persistence/queries.
    # trigger_mode is populated for manual triggers (execution_record_builder.build_execution_record());
    # retry_count is not populated yet and always holds the default below. Baked in
    # now so future retry tracking needs no migration.
    trigger_mode: str | None = None
    """How this execution was triggered (e.g., "manual" for a run-now request). None for
    regular scheduled fires or non-manual handler invocations."""

    retry_count: int = 0
    """Number of retry attempts before this execution. 0 for first attempts."""

    attempt_number: int = 1
    """Ordinal attempt number (1-based). 1 for first attempt."""

    args_json: str = "[]"
    """JSON-encoded positional arguments. '[]' for handler executions."""

    kwargs_json: str = "{}"
    """JSON-encoded keyword arguments. '{}' for handler executions."""
