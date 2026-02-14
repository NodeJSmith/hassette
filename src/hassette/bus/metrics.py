"""Aggregate per-listener metrics for event handler execution tracking.

These are intentionally mutable dataclasses -- they are aggregate counters
modified from the single asyncio thread, so no locking is needed. Creating
frozen copies on every state_changed event would cause unacceptable GC pressure.
"""

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class ListenerMetrics:
    """Aggregate execution metrics for a single event listener."""

    # Identity
    listener_id: int
    owner: str
    topic: str
    handler_name: str

    # Counters
    total_invocations: int = 0
    successful: int = 0
    failed: int = 0
    di_failures: int = 0
    cancelled: int = 0

    # Timing
    total_duration_ms: float = 0.0
    min_duration_ms: float = 0.0
    max_duration_ms: float = 0.0

    # Recency
    last_invoked_at: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None

    @property
    def avg_duration_ms(self) -> float:
        if self.total_invocations == 0:
            return 0.0
        return self.total_duration_ms / self.total_invocations

    def _record_timing(self, duration_ms: float) -> None:
        self.total_invocations += 1
        self.total_duration_ms += duration_ms
        self.last_invoked_at = time.time()

        if self.total_invocations == 1:
            self.min_duration_ms = duration_ms
            self.max_duration_ms = duration_ms
        else:
            if duration_ms < self.min_duration_ms:
                self.min_duration_ms = duration_ms
            if duration_ms > self.max_duration_ms:
                self.max_duration_ms = duration_ms

    def record_success(self, duration_ms: float) -> None:
        self._record_timing(duration_ms)
        self.successful += 1

    def record_error(self, duration_ms: float, message: str, error_type: str) -> None:
        self._record_timing(duration_ms)
        self.failed += 1
        self.last_error_message = message
        self.last_error_type = error_type

    def record_di_failure(self, duration_ms: float, message: str, error_type: str) -> None:
        self._record_timing(duration_ms)
        self.di_failures += 1
        self.last_error_message = message
        self.last_error_type = error_type

    def record_cancelled(self, duration_ms: float) -> None:
        self._record_timing(duration_ms)
        self.cancelled += 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "listener_id": self.listener_id,
            "owner": self.owner,
            "topic": self.topic,
            "handler_name": self.handler_name,
            "total_invocations": self.total_invocations,
            "successful": self.successful,
            "failed": self.failed,
            "di_failures": self.di_failures,
            "cancelled": self.cancelled,
            "avg_duration_ms": self.avg_duration_ms,
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "last_invoked_at": self.last_invoked_at,
            "last_error_message": self.last_error_message,
            "last_error_type": self.last_error_type,
        }
