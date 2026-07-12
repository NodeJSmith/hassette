"""Live runtime state and event payloads for Hassette core services.

This module contains Pydantic ``BaseModel`` classes representing live system
state and WebSocket event data. These are domain objects returned by
``RuntimeQueryService`` and are independent of the web presentation layer.

For DB query result models, see ``telemetry_models.py``.

Separation rationale
--------------------
- ``domain_models.py`` — live state snapshots and WS event payloads (this module)
- ``telemetry_models.py`` — DB query result models (historical/aggregated data)

The web layer (``hassette.web``) maps these domain objects to HTTP/WS response
models via ``hassette.web.mappers``. Core services must NOT import from
``hassette.web``.
"""

import importlib.metadata
from typing import Any, Literal

from pydantic import BaseModel, Field


def _get_hassette_version() -> str:
    """Return the installed hassette package version, or 'unknown' if unavailable."""
    try:
        return importlib.metadata.version("hassette")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


class BootIssue(BaseModel):
    """A single boot-time issue collected during startup."""

    severity: Literal["err", "warn"]
    """Severity level: 'err' for errors, 'warn' for warnings."""

    label: str
    """Short human-readable label (e.g. 'App blocked', 'Config invalid')."""

    detail: str
    """Longer description or context for the issue."""


class ServiceInfo(BaseModel):
    """Structured info for one internal service."""

    name: str
    status: str
    role: str = ""
    """Role of the service (e.g. 'service', 'resource'). Empty string when not available."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted (cooling state), or None."""


class SystemStatus(BaseModel):
    """Live system status snapshot returned by ``RuntimeQueryService.get_system_status()``."""

    status: Literal["ok", "degraded", "starting"]
    """Overall health of the Hassette instance."""

    websocket_connected: bool
    """Whether the Home Assistant WebSocket connection is live."""

    uptime_seconds: float
    """Seconds since startup."""

    entity_count: int
    """Number of HA entities currently tracked."""

    app_count: int
    """Number of running app instances."""

    services: list[ServiceInfo] = Field(default_factory=list)
    """Structured info for all tracked services."""

    version: str = Field(default_factory=_get_hassette_version)
    """Installed hassette package version."""

    boot_issues: list[BootIssue] = Field(default_factory=list)
    """Boot-time issues collected during startup (config errors, blocked apps)."""

    log_records_dropped: int = 0
    """Cumulative count of log records dropped due to queue-full or missing DB."""


class StateChangedData(BaseModel):
    """Payload for a Home Assistant ``state_changed`` event broadcast over WebSocket."""

    entity_id: str
    new_state: dict[str, Any] | None = None
    old_state: dict[str, Any] | None = None


class AppStatusChangedData(BaseModel):
    """Payload for an app lifecycle state-change event broadcast over WebSocket.

    Mirrors ``events.hassette.AppStateChangePayload`` exactly.
    """

    app_key: str
    index: int
    status: str
    previous_status: str | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class ConnectivityData(BaseModel):
    """Payload for a Home Assistant WebSocket connectivity event."""

    connected: bool


class ServiceStatusData(BaseModel):
    """Payload for an internal service status-change event broadcast over WebSocket.

    Mirrors ``events.hassette.ServiceStatusPayload``.
    """

    resource_name: str
    role: str
    status: str
    previous_status: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted.

    Populated for ``EXHAUSTED_COOLING`` events (the service is in a long cooldown
    and will retry at this time). ``None`` for ``EXHAUSTED_DEAD`` and all other
    statuses.  The frontend uses this to display a live countdown timer.
    """
    ready: bool = False
    """Whether the service had signalled readiness at the time of this status event."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""
