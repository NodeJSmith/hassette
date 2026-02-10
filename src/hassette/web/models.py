"""Pydantic response models for the Hassette Web API."""

from typing import Any

from pydantic import BaseModel


class SystemStatusResponse(BaseModel):
    status: str
    websocket_connected: bool
    uptime_seconds: float | None
    entity_count: int
    app_count: int
    services_running: list[str]


class EntityStateResponse(BaseModel):
    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: str | None
    last_updated: str | None


class EntityListResponse(BaseModel):
    count: int
    entities: list[EntityStateResponse]


class AppInstanceResponse(BaseModel):
    app_key: str
    index: int
    instance_name: str
    class_name: str
    status: str
    error_message: str | None = None


class AppStatusResponse(BaseModel):
    total: int
    running: int
    failed: int
    apps: list[AppInstanceResponse]
    only_app: str | None = None


class EventEntry(BaseModel):
    type: str
    entity_id: str | None = None
    timestamp: str
    data: dict[str, Any] = {}


class WsMessage(BaseModel):
    type: str
    data: dict[str, Any]


class LogEntryResponse(BaseModel):
    timestamp: float
    level: str
    logger_name: str
    func_name: str
    lineno: int
    message: str
    exc_info: str | None = None
    app_key: str | None = None


class ScheduledJobResponse(BaseModel):
    job_id: int
    name: str
    owner: str
    next_run: str
    repeat: bool
    cancelled: bool
    trigger_type: str
    timeout_seconds: int


class JobExecutionResponse(BaseModel):
    job_id: int
    job_name: str
    owner: str
    started_at: float
    duration_ms: float
    status: str
    error_message: str | None = None
    error_type: str | None = None
