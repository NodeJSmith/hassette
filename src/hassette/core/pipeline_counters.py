"""One process-wide registry of telemetry pipeline counters (D24.1).

Each counter names a place where the telemetry pipeline drops, samples, or fails to handle a record.
``PipelineCounter`` is a closed enum, so a new counter is a new member here rather than a new private
field plus accessors on the component that owns the site. ``Hassette.pipeline_counters`` holds the
one ``PipelineCounters`` instance for the process.
"""

import threading
from enum import Enum, StrEnum, auto


class CounterKind(StrEnum):
    """What a counted event means for the record involved."""

    LOSS = auto()
    """The record was dropped and never reaches its destination."""

    SAMPLED = auto()
    """The record was skipped on purpose by a sampling or filtering rule."""

    FAILURE = auto()
    """A component failed while handling the record."""


class PipelineCounter(Enum):
    """A counted pipeline site, identified by its stage and the reason it counts."""

    EXECUTION_WRITE_QUEUE_OVERFLOW = ("execution_write_queue", "overflow", CounterKind.LOSS)
    EXECUTION_WRITE_RETRIES_EXHAUSTED = ("execution_write", "retries_exhausted", CounterKind.LOSS)
    EXECUTION_WRITE_SHUTDOWN = ("execution_write", "shutdown", CounterKind.LOSS)
    EXECUTION_WRITE_NON_RETRYABLE_ERROR = ("execution_write", "non_retryable_error", CounterKind.LOSS)
    EXECUTION_WRITE_NO_SESSION = ("execution_write", "no_session", CounterKind.LOSS)
    EXECUTION_WRITE_DRAIN_FAILED = ("execution_write", "drain_failed", CounterKind.LOSS)
    EXECUTION_FILTER_FRAMEWORK_SAMPLED = ("execution_filter", "framework_sampled", CounterKind.SAMPLED)
    ERROR_HANDLER_HANDLER_RAISED = ("error_handler", "handler_raised", CounterKind.FAILURE)
    LOG_QUEUE_OVERFLOW = ("log_queue", "overflow", CounterKind.LOSS)
    LOG_DB_WRITE_QUEUE_OVERFLOW = ("log_db_write_queue", "overflow", CounterKind.LOSS)
    WS_BROADCAST_CLIENT_QUEUE_FULL = ("ws_broadcast", "client_queue_full", CounterKind.LOSS)
    BLOCKING_EVENT_WRITE_OVERFLOW = ("blocking_event_write", "overflow", CounterKind.LOSS)

    def __init__(self, stage: str, reason: str, kind: CounterKind) -> None:
        self.stage = stage
        self.reason = reason
        self.kind = kind


class PipelineCounters:
    """Thread-safe counts for every ``PipelineCounter``, all starting at zero.

    Log handlers increment from non-loop threads, so every read and write takes the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[PipelineCounter, int] = dict.fromkeys(PipelineCounter, 0)

    def increment(self, counter: PipelineCounter, n: int = 1) -> None:
        """Add ``n`` to ``counter``."""
        with self._lock:
            self._counts[counter] += n

    def get(self, counter: PipelineCounter) -> int:
        """Return the current count for ``counter``."""
        with self._lock:
            return self._counts[counter]

    def snapshot(self) -> dict[PipelineCounter, int]:
        """Return a copy of every counter's current count, taken under one lock acquisition."""
        with self._lock:
            return dict(self._counts)
