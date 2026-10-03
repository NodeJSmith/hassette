from typing import Annotated, Literal

from hassette_wire.lenient import LenientValue, UnknownValue

SourceTier = Literal["app", "framework"]
"""Identifies whether a telemetry record originates from a user app or the framework itself."""

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
"""Log levels for configuring logging."""

QuerySourceTier = Literal["app", "framework", "all"]
"""Valid source_tier values for query-side filtering. 'all' disables the filter."""

ErrorRateClass = Literal["good", "warn", "bad"]
"""CSS classification for error rate percentage."""

OpenErrorRateClass = Annotated[ErrorRateClass | UnknownValue, LenientValue("ErrorRateClass")]

HealthStatus = Literal["excellent", "good", "warning", "critical"]
"""Health bar classification from success-rate percentage.

Does NOT include ``"unknown"`` — zero-invocation apps return ``"excellent"``.
"""

OpenHealthStatus = Annotated[HealthStatus | UnknownValue, LenientValue("HealthStatus")]

ListenerKind = Literal["state change", "service call", "event"]
"""Kind of listener event (3 values)."""

OpenListenerKind = Annotated[ListenerKind | UnknownValue, LenientValue("ListenerKind")]

SystemHealthStatus = Literal["ok", "degraded", "starting"]
"""System-level health status (3 values).

Mirrors ``SystemStatusResponse.status`` defined in this package (``health.py``).
"""

OpenSystemHealthStatus = Annotated[SystemHealthStatus | UnknownValue, LenientValue("SystemHealthStatus")]

ExecutionKind = Literal["handler", "job"]
"""Whether an execution is a bus handler invocation or a scheduled-job execution."""

OpenExecutionKind = Annotated[ExecutionKind | UnknownValue, LenientValue("ExecutionKind")]

BootIssueSeverity = Literal["err", "warn"]
"""Severity of a boot-time issue."""

OpenBootIssueSeverity = Annotated[BootIssueSeverity | UnknownValue, LenientValue("BootIssueSeverity")]

HandlerKind = Literal["listener", "job"]
"""Whether a handler reference names a bus listener or a scheduled job."""

OpenHandlerKind = Annotated[HandlerKind | UnknownValue, LenientValue("HandlerKind")]
