from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.cli_format import CliFormat
from hassette_wire.enums import OpenResourceRole, OpenResourceStatus
from hassette_wire.literals import OpenBootIssueSeverity, OpenSystemHealthStatus


class BootIssueResponse(BaseModel):
    """A boot-time issue entry in the system status response."""

    severity: OpenBootIssueSeverity
    label: str
    detail: str


class ServiceInfoResponse(BaseModel):
    """Structured info for one internal service."""

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
    model_config = ConfigDict(use_attribute_docstrings=True)

    status: OpenSystemHealthStatus
    websocket_connected: bool
    bootstrap_released: bool
    uptime_seconds: Annotated[float, CliFormat("uptime")]
    entity_count: int
    app_count: int
    services: Annotated[list[ServiceInfoResponse], CliFormat("services")] = Field(default_factory=list)
    version: str = ""
    boot_issues: list[BootIssueResponse] = Field(default_factory=list)
    log_queue_drops: int = 0
    """Log records dropped because the log queue was full — tune ``logging.log_queue_max``."""

    db_write_queue_drops: int = 0
    """Log records dropped because the DB write queue was full, unavailable, or closed."""

    log_persistence_active: bool = False
    """Whether log records are being persisted. When ``False``, a ``db_write_queue_drops`` of 0 does not mean
    logs are being stored."""


class LivenessResponse(BaseModel):
    """Response model for GET /api/health/live."""

    status: Literal["live"] = "live"


class ReadinessResponse(BaseModel):
    """Response model for GET /api/health/ready."""

    status: OpenSystemHealthStatus
    ready: bool
