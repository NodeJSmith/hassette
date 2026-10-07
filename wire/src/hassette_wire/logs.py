from pydantic import BaseModel, ConfigDict, Field

from hassette_wire.literals import LogLevel, OpenExecutionKind, SourceTier


class LogEntry(BaseModel):
    """One captured log record.

    ``id`` identifies the stored record; ``seq`` orders records emitted by one server run. ``app_key``
    and ``instance_*`` are set for records an app emitted and ``None`` for framework records.
    ``execution_*``, ``listener_id`` and ``job_id`` are set only for records emitted while a handler or
    job was running.
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
    instance_index: int | None = None
    source_tier: SourceTier | None = None
    execution_kind: OpenExecutionKind | None = None
    listener_id: int | None = None
    job_id: int | None = None


class LogsByExecutionResponse(BaseModel):
    """The log records one handler or job execution emitted, served by ``GET /api/executions/{execution_id}``."""

    model_config = ConfigDict(use_attribute_docstrings=True)

    records: list[LogEntry]
    truncated: bool
    """``True`` when the execution emitted more records than the request's limit; the rest are omitted."""
    retention_expired: bool
    """``True`` when ``records`` is empty and the execution is older than the server's log retention window:
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
