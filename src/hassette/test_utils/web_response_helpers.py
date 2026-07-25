"""Reusable factory functions for web API response test data."""

from typing import Any

import tomli_w

from hassette.config.models import DEFAULT_WEB_API_PORT
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY
from hassette.test_utils.web_telemetry_helpers import SYNTHETIC_TIMESTAMP
from hassette.web.models import (
    AppConfigResponse,
    AppHealthResponse,
    AppSourceResponse,
    ConfigSchemaResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    SystemStatusResponse,
    TelemetryStatusResponse,
)


def make_system_status_response(
    status: str = "ok",
    websocket_connected: bool = True,
    uptime_seconds: float = 3600.0,
    entity_count: int = 120,
    app_count: int = 3,
    version: str = "0.1.0",
) -> SystemStatusResponse:
    """Build a SystemStatusResponse with sensible defaults."""
    return SystemStatusResponse(
        status=status,  # pyright: ignore[reportArgumentType]
        websocket_connected=websocket_connected,
        uptime_seconds=uptime_seconds,
        entity_count=entity_count,
        app_count=app_count,
        version=version,
    )


def make_telemetry_status_response(
    degraded: bool = False,
    dropped_overflow: int = 0,
    dropped_exhausted: int = 0,
    dropped_shutdown: int = 0,
    error_handler_failures: int = 0,
) -> TelemetryStatusResponse:
    """Build a TelemetryStatusResponse with sensible defaults."""
    return TelemetryStatusResponse(
        degraded=degraded,
        dropped_overflow=dropped_overflow,
        dropped_exhausted=dropped_exhausted,
        dropped_shutdown=dropped_shutdown,
        error_handler_failures=error_handler_failures,
    )


def make_dashboard_app_grid_entry(
    app_key: str = DEFAULT_TEST_APP_KEY,
    status: str = "running",
    display_name: str = "Test App",
    instance_count: int = 1,
    handler_count: int = 2,
    job_count: int = 1,
    total_invocations: int = 100,
    total_errors: int = 0,
    total_executions: int = 50,
    total_job_errors: int = 0,
    avg_duration_ms: float = 5.0,
    last_activity_ts: float | None = None,
    health_status: str = "excellent",
    error_rate: float = 0.0,
    error_rate_class: str = "good",
) -> DashboardAppGridEntry:
    """Build a DashboardAppGridEntry with sensible defaults."""
    return DashboardAppGridEntry(
        app_key=app_key,
        status=status,  # pyright: ignore[reportArgumentType]
        display_name=display_name,
        instance_count=instance_count,
        handler_count=handler_count,
        job_count=job_count,
        total_invocations=total_invocations,
        total_errors=total_errors,
        total_executions=total_executions,
        total_job_errors=total_job_errors,
        avg_duration_ms=avg_duration_ms,
        last_activity_ts=last_activity_ts,
        health_status=health_status,  # pyright: ignore[reportArgumentType]
        error_rate=error_rate,
        error_rate_class=error_rate_class,  # pyright: ignore[reportArgumentType]
    )


def make_dashboard_app_grid_response(
    entries: list[DashboardAppGridEntry] | None = None,
) -> DashboardAppGridResponse:
    """Build a DashboardAppGridResponse from a list of entries."""
    return DashboardAppGridResponse(apps=entries or [make_dashboard_app_grid_entry()])


def make_config_schema_response() -> ConfigSchemaResponse:
    """Build a ConfigSchemaResponse with sensible defaults for testing.

    Returns a representative envelope containing a stub schema and a values dict
    that covers every config group — including ``database``, ``websocket``, and
    ``blocking_io``, the groups the old global endpoint omitted.
    """
    return ConfigSchemaResponse(
        config_schema={
            "type": "object",
            "properties": {"web_api": {"type": "object"}, "dev_mode": {"type": "boolean"}},
        },
        config_values={
            "dev_mode": False,
            "base_url": "http://homeassistant.local:8123",
            "asyncio_debug_mode": False,
            "allow_reload_in_prod": False,
            "token": None,
            "data_dir": "/home/user/.local/share/hassette",
            "config_dir": "/home/user/.config/hassette",
            "web_api": {
                "run": True,
                "run_ui": True,
                "ui_hot_reload": False,
                "host": "0.0.0.0",
                "port": DEFAULT_WEB_API_PORT,
                "cors_origins": [],
                "log_buffer_size": 500,
                "job_history_size": 100,
            },
            "logging": {"log_level": "INFO", "web_api": "WARNING"},
            "lifecycle": {
                "startup_timeout_seconds": 30,
                "app_startup_timeout_seconds": 10,
                "app_shutdown_timeout_seconds": 10,
            },
            "apps": {"autodetect": True, "directory": "apps"},
            "scheduler": {"min_delay_seconds": 0, "max_delay_seconds": 3600, "default_delay_seconds": 0},
            "file_watcher": {"watch_files": True, "debounce_milliseconds": 500},
            "database": {"retention_days": 7, "max_size_mb": 500},
            "websocket": {"reconnect_delay_seconds": 5, "max_reconnect_attempts": 10},
            "blocking_io": {"enabled": True, "warn_threshold_ms": 100},
        },
    )


def make_app_health_response(
    error_rate: float = 0.0,
    error_rate_class: str = "good",
    handler_avg_duration: float = 5.0,
    job_avg_duration: float = 10.0,
    last_activity_ts: float | None = SYNTHETIC_TIMESTAMP,
    health_status: str = "excellent",
) -> AppHealthResponse:
    """Build an AppHealthResponse with sensible defaults."""
    return AppHealthResponse(
        error_rate=error_rate,
        error_rate_class=error_rate_class,  # pyright: ignore[reportArgumentType]
        handler_avg_duration=handler_avg_duration,
        job_avg_duration=job_avg_duration,
        last_activity_ts=last_activity_ts,
        health_status=health_status,  # pyright: ignore[reportArgumentType]
    )


def _strip_none(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_none(v) for v in obj if v is not None]
    return obj


def _config_to_toml(app_key: str, app_config: dict[str, Any] | list[dict[str, Any]]) -> str:
    toml_wrapper: dict[str, Any] = {"hassette": {"apps": {app_key: {"config": _strip_none(app_config)}}}}
    return tomli_w.dumps(toml_wrapper)


def make_app_config_response(
    app_key: str = DEFAULT_TEST_APP_KEY,
    filename: str = "test_app.py",
    class_name: str = "TestApp",
    enabled: bool = True,
    autostart: bool = True,
    app_config: dict | list[dict] | None = None,
    config_schema: dict | None = None,
    framework_fields: list[str] | None = None,
) -> AppConfigResponse:
    """Build an AppConfigResponse with sensible defaults."""
    resolved_config = app_config if app_config is not None else {"setting_name": "default"}
    return AppConfigResponse(
        app_key=app_key,
        filename=filename,
        class_name=class_name,
        enabled=enabled,
        autostart=autostart,
        app_config=resolved_config,
        config_toml=_config_to_toml(app_key, resolved_config),
        config_schema=config_schema,
        framework_fields=framework_fields if framework_fields is not None else [],
    )


def make_app_source_response(
    app_key: str = DEFAULT_TEST_APP_KEY,
    filename: str = "test_app.py",
    content: str = "class TestApp:\n    pass\n",
    line_count: int = 2,
) -> AppSourceResponse:
    """Build an AppSourceResponse with sensible defaults."""
    return AppSourceResponse(
        app_key=app_key,
        filename=filename,
        content=content,
        line_count=line_count,
    )
