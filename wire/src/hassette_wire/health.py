from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.cli_format import CliFormat
from hassette_wire.enums import OpenResourceRole, OpenResourceStatus
from hassette_wire.literals import OpenBootIssueSeverity, OpenLivenessStatus, OpenSystemHealthStatus

API_SCHEMA_VERSION = 1
"""The API schema this server serves, reported as ``SystemStatusResponse.api_schema_version``.

An integer, not a release version, so a build from main reports the API it actually serves. hassette-client
compares it against its ``MIN_API_SCHEMA_VERSION``; see that constant for when to raise this one.
"""


class BootIssue(BaseModel):
    """A problem found while the server started, listed in ``SystemStatusResponse.boot_issues``."""

    severity: OpenBootIssueSeverity
    label: str
    detail: str


class ServiceInfo(BaseModel):
    """One framework service and its lifecycle status, listed in ``SystemStatusResponse.services``."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    name: str
    status: OpenResourceStatus
    role: OpenResourceRole
    """What kind of framework component the service is."""
    ready_phase: str | None = None
    """Human-readable description of the current readiness phase, or None if not available."""
    retry_at: float | None = None
    """Unix timestamp when the next restart will be attempted (cooling state), or None."""


class SystemStatusResponse(BaseModel):
    """Overall server health, served by ``GET /api/health``."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    status: OpenSystemHealthStatus
    websocket_connected: bool
    bootstrap_released: bool
    uptime_seconds: Annotated[float, CliFormat("uptime")]
    entity_count: int
    app_count: Annotated[int, CliFormat("instance_count")]
    """Number of app instances currently tracked, running or failed — not the number of configured apps.

    A configured app that is stopped, disabled, or not yet started has no instance and is not counted, so this
    is ``0`` before app bootstrap and can be lower than the total ``GET /api/apps`` lists."""
    services: Annotated[list[ServiceInfo], CliFormat("services")] = Field(default_factory=list)
    version: str = ""
    api_schema_version: int = 0
    """The server's ``API_SCHEMA_VERSION``; ``0`` from a server released before the schema existed."""
    boot_issues: list[BootIssue] = Field(default_factory=list)
    log_queue_drops: int = 0
    """Log records dropped because the log queue was full — tune ``logging.log_queue_max``."""

    db_write_queue_drops: int = 0
    """Log records dropped because the DB write queue was full, unavailable, or closed."""

    log_persistence_active: bool = False
    """Whether log records are being persisted. When ``False``, a ``db_write_queue_drops`` of 0 does not mean
    logs are being stored."""


class LivenessResponse(BaseModel):
    """Response model for GET /api/health/live."""

    status: OpenLivenessStatus


class ReadinessResponse(BaseModel):
    """Response model for GET /api/health/ready."""

    status: OpenSystemHealthStatus
    ready: bool
