from pydantic import BaseModel

from hassette_wire.literals import LogLevel, OpenExecutionKind, SourceTier


class LogEntryResponse(BaseModel):
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
    """Response for GET /api/executions/{execution_id}."""

    records: list[LogEntryResponse]
    truncated: bool
    retention_expired: bool


class LogLevelRequest(BaseModel):
    """Request body for PUT /api/logs/level."""

    logger: str
    level: str


class LogLevelResponse(BaseModel):
    """Response for PUT /api/logs/level."""

    logger: str
    effective_level: str
