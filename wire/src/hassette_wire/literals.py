from typing import Literal

SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself."""

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""

ErrorRateClass = Literal["good", "warn", "bad"]
"""CSS classification for error rate percentage.

Verified against ``classify_error_rate()`` return values in ``telemetry_helpers.py``.
"""

HealthStatus = Literal["excellent", "good", "warning", "critical"]
"""Health bar classification from success-rate percentage.

Verified against ``classify_health_bar()`` return values in ``telemetry_helpers.py``.
Does NOT include ``"unknown"`` — zero-invocation apps return ``"excellent"``.
"""

ListenerKind = Literal["state change", "service call", "event"]
"""Kind of listener event (3 values).

Verified against ``listener_kind_from_topic()`` return values in ``mappers.py``.
"""

SystemHealthStatus = Literal["ok", "degraded", "starting"]
"""System-level health status (3 values).

Mirrors ``SystemStatusResponse.status`` defined in this package (``health.py``).
"""
