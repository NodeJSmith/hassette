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

from typing import Any, Literal

from pydantic import BaseModel


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

    services_running: list[str]
    """Names of internal services currently in RUNNING state."""


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
