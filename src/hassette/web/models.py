"""Pydantic response models for the Hassette Web API."""

from typing import Any

from pydantic import BaseModel, Field


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
    owner_id: str | None = None


class AppStatusResponse(BaseModel):
    total: int
    running: int
    failed: int
    apps: list[AppInstanceResponse]
    only_app: str | None = None


class AppManifestResponse(BaseModel):
    app_key: str
    class_name: str
    display_name: str
    filename: str
    enabled: bool
    auto_loaded: bool
    status: str
    block_reason: str | None = None
    instance_count: int = 0
    instances: list[AppInstanceResponse] = Field(default_factory=list)
    error_message: str | None = None


class AppManifestListResponse(BaseModel):
    total: int
    running: int
    failed: int
    stopped: int
    disabled: int
    blocked: int
    manifests: list[AppManifestResponse]
    only_app: str | None = None


class EventEntry(BaseModel):
    type: str
    entity_id: str | None = None
    timestamp: float
    data: dict[str, Any] = Field(default_factory=dict)


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


class ListenerMetricsResponse(BaseModel):
    listener_id: int
    owner: str
    topic: str
    handler_name: str
    total_invocations: int
    successful: int
    failed: int
    di_failures: int
    cancelled: int
    avg_duration_ms: float
    min_duration_ms: float
    max_duration_ms: float
    total_duration_ms: float
    last_invoked_at: float | None = None
    last_error_message: str | None = None
    last_error_type: str | None = None


class BusMetricsSummaryResponse(BaseModel):
    total_listeners: int
    total_invocations: int
    total_successful: int
    total_failed: int
    total_di_failures: int
    total_cancelled: int
