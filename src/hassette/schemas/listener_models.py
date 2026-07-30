"""Pydantic models for listener (handler) telemetry DB query results.

These typed models replace raw ``dict`` returns, preventing the
"column rename -> silent template failure" class of bugs.

For live runtime state models, see ``domain_models.py``.

See ``schemas/__init__.py`` for the domain-file map.
"""

from typing import Literal

from pydantic import BaseModel

from hassette.types.enums import (
    DEFAULT_BACKPRESSURE_POLICY,
    DEFAULT_EVENT_PRIORITY,
    DEFAULT_OVERLAP_MODE,
    BackpressurePolicy,
    EventPriority,
    ExecutionMode,
)
from hassette.types.types import SourceTier


class ListenerSummary(BaseModel):
    """Per-listener summary returned by ``get_listener_summary()``.

    ``failed`` counts only ``'error'`` status; ``timed_out`` and ``cancelled`` are tracked separately.
    Invariant: ``successful + failed + cancelled + timed_out == total_invocations``.
    """

    listener_id: int
    app_key: str
    instance_index: int
    handler_method: str
    topic: str
    debounce: float | None
    throttle: float | None
    once: int
    priority: int
    predicate_description: str | None
    human_description: str | None
    source_location: str
    registration_source: str | None
    source_tier: SourceTier = "app"
    immediate: int = 0
    duration: float | None = None
    entity_id: str | None = None
    mode: ExecutionMode = DEFAULT_OVERLAP_MODE
    backpressure: BackpressurePolicy = DEFAULT_BACKPRESSURE_POLICY
    """Sourced from the ``listeners.backpressure`` column; ``'block'`` (default) or ``'drop_newest'``."""
    event_priority: EventPriority = DEFAULT_EVENT_PRIORITY
    """Sourced from the ``listeners.event_priority`` column; ``'low'``, ``'normal'`` (default),
    ``'high'``, or ``'critical'``."""
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    timed_out: int = 0
    thread_leaked: int = 0
    """Number of invocations whose sync worker thread outlived its timeout (see ``Execution.thread_leaked``).
    Aggregated from the ``executions`` table; a non-zero value flags a handler leaking worker threads.
    Mirrors the ``timed_out`` aggregate naming — the bare participle, not a ``_count`` suffix."""
    total_duration_ms: float
    avg_duration_ms: float
    min_duration_ms: float | None = None
    max_duration_ms: float | None = None
    last_invoked_at: float | None
    last_error_type: str | None
    last_error_message: str | None
    last_error_traceback: str | None = None


class ListenerGlobalStats(BaseModel):
    """Listener aggregate stats within ``GlobalSummary``."""

    total_listeners: int
    invoked_listeners: int
    total_invocations: int
    total_errors: int
    total_timed_out: int = 0
    total_di_failures: int
    avg_duration_ms: float | None


class HandlerErrorRecord(BaseModel):
    """Handler error returned by ``get_recent_errors()``."""

    kind: Literal["handler"] = "handler"
    listener_id: int | None
    app_key: str | None
    handler_method: str | None
    topic: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier = "app"
    error_type: str | None
    error_message: str | None
    error_traceback: str | None = None
    source_location: str | None = None
    """Source file location of the handler (e.g. 'my_app.py:42')."""


class SlowHandlerRecord(BaseModel):
    """Slow handler invocation returned by ``get_slow_handlers()``.

    ``app_key``, ``handler_method``, and ``topic`` are nullable because
    ``get_slow_handlers`` uses a LEFT JOIN.  Orphaned invocations (whose
    listener row was deleted) are still returned with ``None`` for these fields.
    """

    app_key: str | None
    handler_method: str | None
    topic: str | None
    execution_start_ts: float
    duration_ms: float
    source_tier: SourceTier
