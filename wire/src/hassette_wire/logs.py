from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.literals import LogAuthor, LogLevel, OpenExecutionKind
from hassette_wire.telemetry import ApiWrite, Execution


class LogEntry(BaseModel):
    """One captured log record.

    ``id`` identifies the stored record; ``seq`` orders records emitted by one server run. ``app_key``
    and ``instance_*`` are set for records an app emitted and ``None`` for framework records.
    ``execution_*``, ``listener_id`` and ``job_id`` are set only for records emitted while a handler or
    job was running. ``author`` says who wrote the line: ``"app"`` for an app's own code, ``"framework"`` for
    Hassette's, including its lines about an app.
    """

    id: int
    seq: int
    timestamp: float
    level: LogLevel
    logger_name: str
    func_name: str | None = None
    lineno: int | None = None
    message: str
    exc_info: str | None = None
    app_key: str | None = None
    execution_id: str | None = None
    instance_name: str | None = None
    author: LogAuthor | None = None
    execution_kind: OpenExecutionKind | None = None
    listener_id: int | None = None
    job_id: int | None = None


class ExecutionDetailResponse(BaseModel):
    """One handler or job execution: its record, the API writes it made, and its log records.

    Served by ``GET /api/executions/{execution_id}``. ``api_writes`` and ``logs`` are each capped by the request's
    ``limit``.
    """

    model_config = ConfigDict(use_attribute_docstrings=True)

    execution: Execution | None
    """The execution record. None while it isn't recorded yet (records are written in batches, so it can lag the
    logs by a few seconds) or after retention removed it."""
    api_writes: list[ApiWrite]
    """The writes the execution sent to Home Assistant, oldest first."""
    api_writes_truncated: bool
    """``True`` when the execution made more writes than the request's limit; the rest are omitted."""
    logs: list[LogEntry]
    """The log records the execution emitted, oldest first."""
    logs_truncated: bool
    """``True`` when the execution emitted more records than the request's limit; the rest are omitted."""
    retention_expired: bool
    """``True`` when ``logs`` is empty and the execution is older than the server's log retention window:
    its records may have been deleted, or it may never have logged."""


class LogLevelRequest(BaseModel):
    """Request body for PUT /api/logs/level."""

    logger: str
    level: str = Field(
        description="Level name to set: DEBUG, INFO, WARNING, ERROR, or CRITICAL. Case-insensitive.",
    )


class LogLevelResponse(BaseModel):
    """Response for PUT /api/logs/level."""

    logger: str
    effective_level: LogLevel
