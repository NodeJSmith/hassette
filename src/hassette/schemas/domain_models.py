"""Live runtime state and event payloads for Hassette core services.

This module contains Pydantic ``BaseModel`` classes representing live system
state and WebSocket event data. These are domain objects returned by
``RuntimeQueryService`` and are independent of the web presentation layer.

For DB query result models, see the domain-grouped sibling files:
``listener_models.py``, ``execution_models.py``, ``job_models.py``,
``summary_models.py``, and ``log_models.py``.

Separation rationale
--------------------
- ``domain_models.py`` — live state snapshots and WS event payloads (this module)
- ``listener_models.py`` — per-listener summaries, stats, and error records
- ``execution_models.py`` — unified execution records and activity feed
- ``job_models.py`` — per-job summaries, stats, and error records
- ``summary_models.py`` — app-health and global aggregates
- ``log_models.py`` — log records and blocking events

The web layer (``hassette.web``) maps these domain objects to HTTP/WS response
models via ``hassette.web.mappers``. Core services must NOT import from
``hassette.web``.
"""

from typing import Literal

from pydantic import BaseModel, Field

from hassette.types.enums import ResourceStatus
from hassette.utils import get_version


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

    bootstrap_released: bool
    """Whether AppBootstrapCoordinator has released app bootstrap.

    False while apps are configured but blocked waiting on Home Assistant connectivity and
    initial state capability. Once true, remains true for the rest of the process lifetime
    even across later WebSocket disconnects.
    """

    uptime_seconds: float
    """Seconds since startup."""

    entity_count: int
    """Number of HA entities currently tracked."""

    app_count: int
    """Number of running app instances."""

    services: list[ServiceInfo] = Field(default_factory=list)
    """Structured info for all tracked services."""

    version: str = Field(default_factory=get_version)
    """Installed hassette package version."""

    boot_issues: list[BootIssue] = Field(default_factory=list)
    """Boot-time issues collected during startup (config errors, blocked apps)."""

    log_queue_drops: int = 0
    """Cumulative count of log records dropped because the log queue was full."""

    db_write_queue_drops: int = 0
    """Cumulative count of records dropped because the DB write queue was full, unavailable, or closed."""

    log_persistence_active: bool = False
    """Whether log records are currently being persisted.

    False means log persistence is unavailable, so ``db_write_queue_drops`` of 0 reflects a
    dead pipeline rather than a healthy one.
    """


class AppStatusChangedData(BaseModel):
    """Payload for an app lifecycle state-change event broadcast over WebSocket.

    Mirrors ``events.hassette.AppStateChangePayload`` exactly.
    """

    app_key: str
    index: int
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
    instance_name: str | None = None
    class_name: str | None = None
    exception: str | None = None
    exception_type: str | None = None
    exception_traceback: str | None = None


class ConnectivityData(BaseModel):
    """Payload for a Home Assistant WebSocket connectivity event."""

    connected: bool


class AppManifestsChangedData(BaseModel):
    """Payload for a manifest refresh broadcast over WebSocket.

    Carries no fields — it is a refetch signal, not a diff. The event that triggers it
    (``HASSETTE_EVENT_APP_LOAD_COMPLETED``) fires after a full bootstrap or reload pass over
    all apps, and also after a live config edit that only changes manifest metadata (e.g.
    ``display_name``) with no lifecycle action to take. Either way it does not identify which
    app(s) changed, so clients should treat receipt as "manifest status may be stale, refetch"
    rather than inspect the payload for detail.
    """


class ServiceStatusData(BaseModel):
    """Payload for an internal service status-change event broadcast over WebSocket.

    Mirrors ``events.hassette.ServiceStatusPayload``.
    """

    resource_name: str
    role: str
    status: ResourceStatus
    previous_status: ResourceStatus | None = None
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
