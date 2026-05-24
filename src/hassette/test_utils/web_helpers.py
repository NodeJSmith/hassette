"""Reusable factory functions for web-related test data.

These build manifest, snapshot, listener-metric, and registry objects
used by both e2e and integration web tests.

**Factory guide**:

- ``make_job()`` — builds a ``SimpleNamespace`` job stub with a real trigger object.
  Use for web/serialization tests that only need duck-typed attribute access.
- ``make_real_job()`` — builds a real ``ScheduledJob`` instance.
  Use for tests that exercise ``ScheduledJob.__post_init__``, ``matches()``,
  ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
"""

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

from whenever import ZonedDateTime

import hassette.utils.date_utils as date_utils
from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.core.telemetry_models import ActivityFeedEntry
from hassette.scheduler.classes import ScheduledJob
from hassette.scheduler.triggers import After, Cron, Every, Once
from hassette.types.types import InvocationStatus
from hassette.web.models import (
    AppConfigResponse,
    AppHealthResponse,
    AppInstanceResponse,
    AppManifestListResponse,
    AppManifestResponse,
    AppsConfigResponse,
    AppSourceResponse,
    ConfigResponse,
    DashboardAppGridEntry,
    DashboardAppGridResponse,
    EventEntry,
    FileWatcherConfigResponse,
    LifecycleConfigResponse,
    LoggingConfigResponse,
    SchedulerConfigResponse,
    SystemStatusResponse,
    TelemetryStatusResponse,
    WebApiConfigResponse,
)


def make_full_snapshot(
    manifests: list[AppManifestInfo] | None = None,
    only_app: str | None = None,
) -> AppFullSnapshot:
    """Build an AppFullSnapshot from a list of manifests."""
    manifests = manifests or []
    counts = {"running": 0, "failed": 0, "stopped": 0, "disabled": 0, "blocked": 0}
    for m in manifests:
        if m.status in counts:
            counts[m.status] += 1
    return AppFullSnapshot(
        manifests=manifests,
        only_app=only_app,
        total=len(manifests),
        **counts,
    )


def make_manifest(
    app_key: str = "my_app",
    class_name: str = "MyApp",
    display_name: str = "My App",
    filename: str = "my_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: str = "running",
    block_reason: str | None = None,
    instance_count: int = 1,
    instances: list[AppInstanceInfo] | None = None,
    error_message: str | None = None,
    error_traceback: str | None = None,
) -> AppManifestInfo:
    """Build an AppManifestInfo with sensible defaults."""
    return AppManifestInfo(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        block_reason=block_reason,
        instance_count=instance_count,
        instances=instances or [],
        error_message=error_message,
        error_traceback=error_traceback,
    )


def make_manifest_response(
    app_key: str = "my_app",
    class_name: str = "MyApp",
    display_name: str = "My App",
    filename: str = "my_app.py",
    enabled: bool = True,
    auto_loaded: bool = False,
    status: str = "running",
    instance_count: int = 1,
    instances: list[AppInstanceResponse] | None = None,
) -> AppManifestResponse:
    """Build an AppManifestResponse with sensible defaults."""
    return AppManifestResponse(
        app_key=app_key,
        class_name=class_name,
        display_name=display_name,
        filename=filename,
        enabled=enabled,
        auto_loaded=auto_loaded,
        status=status,
        instance_count=instance_count,
        instances=instances or [],
    )


def make_manifest_list_response(
    manifests: list[AppManifestResponse] | None = None,
) -> AppManifestListResponse:
    """Build an AppManifestListResponse from a list of manifests."""
    manifests = manifests or []
    counts = {"running": 0, "failed": 0, "stopped": 0, "disabled": 0, "blocked": 0}
    for m in manifests:
        if m.status in counts:
            counts[m.status] += 1
    return AppManifestListResponse(
        manifests=manifests,
        total=len(manifests),
        **counts,
    )


def make_listener_metric(
    listener_id: int,
    app_key: str,
    topic: str,
    handler_method: str,
    instance_index: int = 0,
    invocations: int = 10,
    successful: int = 9,
    failed: int = 1,
    predicate_description: str | None = None,
    debounce: float | None = None,
    throttle: float | None = None,
    once: bool = False,
    priority: int = 0,
) -> MagicMock:
    """Build a mock listener metric with `.to_dict()` and direct attribute access."""
    d = {
        "listener_id": listener_id,
        "app_key": app_key,
        "instance_index": instance_index,
        "topic": topic,
        "handler_method": handler_method,
        "total_invocations": invocations,
        "successful": successful,
        "failed": failed,
        "di_failures": 0,
        "cancelled": 0,
        "total_duration_ms": invocations * 2.0,
        "min_duration_ms": 1.0,
        "max_duration_ms": 5.0,
        "avg_duration_ms": 2.0,
        "predicate_description": predicate_description,
        "debounce": debounce,
        "throttle": throttle,
        "once": once,
        "priority": priority,
        "last_invoked_at": None,
        "last_error_message": None,
        "last_error_type": None,
    }
    m = MagicMock()
    m.to_dict.return_value = d
    # Expose attributes directly for mock attribute access
    for k, v in d.items():
        setattr(m, k, v)
    return m


def setup_registry(hassette: MagicMock, manifests: list[AppManifestInfo] | None = None) -> None:
    """Configure the mock registry to return a proper AppFullSnapshot."""
    snapshot = make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot


# ──────────────────────────────────────────────────────────────────────
# Scheduler job factory
# ──────────────────────────────────────────────────────────────────────


def make_job(
    job_id: str = "job-1",
    name: str = "check_lights",
    owner_id: str = "MyApp.MyApp[0]",
    next_run: str = "2024-01-01T00:05:00",
    trigger_type: str = "interval",
    trigger_detail: str | None = None,
    db_id: int | None = None,
    app_key: str = "",
    instance_index: int = 0,
) -> SimpleNamespace:
    """Build a ``SimpleNamespace`` scheduler job for test fixtures.

    Uses real trigger objects (``Every``, ``Cron``, ``Once``, ``After``) that
    implement ``TriggerProtocol`` so that ``resolve_trigger()`` works via the
    ``trigger_db_type()`` path.
    """
    trigger: object
    if trigger_type == "cron":
        cron_expr = trigger_detail or "0 0 * * *"
        trigger = Cron(cron_expr)
    elif trigger_type == "interval":
        seconds = 30
        if trigger_detail is not None:
            # Parse ISO 8601 duration like "PT30S" → 30 seconds
            m = re.search(r"(\d+)S", trigger_detail)
            if m:
                seconds = int(m.group(1))
        trigger = Every(seconds=seconds)
    elif trigger_type == "once":
        trigger = Once(at=ZonedDateTime.from_system_tz(2030, 1, 1, 0, 0, 0))
    elif trigger_type == "after":
        trigger = After(seconds=30)
    else:
        trigger = None
    return SimpleNamespace(
        job_id=job_id,
        db_id=db_id,
        name=name,
        owner_id=owner_id,
        app_key=app_key,
        instance_index=instance_index,
        next_run=next_run,
        trigger=trigger,
    )


def make_real_job(
    name: str = "test_job",
    owner_id: str = "MyApp.MyApp[0]",
    trigger: object | None = None,
    jitter: float | None = None,
    group: str | None = None,
    app_key: str = "",
    instance_index: int = 0,
) -> ScheduledJob:
    """Build a real ``ScheduledJob`` instance for tests that need full object behavior.

    Use this instead of ``make_job()`` when the test exercises ``ScheduledJob.__post_init__``,
    ``matches()``, ``sort_index``, ``set_next_run``, or ``fire_at`` behavior.
    Use ``make_job()`` for web/serialization tests that only need duck-typed attribute access.

    Args:
        name: Job name. Defaults to ``"test_job"``.
        owner_id: Owner ID. Defaults to ``"MyApp.MyApp[0]"``.
        trigger: Optional trigger. Defaults to ``None``.
        jitter: Optional jitter in seconds.
        group: Optional group name.
        app_key: Optional app key.
        instance_index: Optional app instance index.
    """
    return ScheduledJob(
        owner_id=owner_id,
        next_run=date_utils.now(),
        job=lambda: None,
        name=name,
        trigger=trigger,  # pyright: ignore[reportArgumentType]
        jitter=jitter,
        group=group,
        app_key=app_key,
        instance_index=instance_index,
    )


# ──────────────────────────────────────────────────────────────────────
# CLI response model factories (used by T05+ tests)
# ──────────────────────────────────────────────────────────────────────


def make_system_status_response(
    status: str = "ok",
    websocket_connected: bool = True,
    uptime_seconds: float = 3600.0,
    entity_count: int = 120,
    app_count: int = 3,
    version: str = "0.1.0",
    services_running: list[str] | None = None,
) -> SystemStatusResponse:
    """Build a SystemStatusResponse with sensible defaults."""
    return SystemStatusResponse(
        status=status,  # pyright: ignore[reportArgumentType]
        websocket_connected=websocket_connected,
        uptime_seconds=uptime_seconds,
        entity_count=entity_count,
        app_count=app_count,
        version=version,
        services_running=services_running or ["websocket", "db"],
    )


def make_telemetry_status_response(
    degraded: bool = False,
    dropped_overflow: int = 0,
    dropped_exhausted: int = 0,
    dropped_no_session: int = 0,
    dropped_shutdown: int = 0,
    error_handler_failures: int = 0,
) -> TelemetryStatusResponse:
    """Build a TelemetryStatusResponse with sensible defaults."""
    return TelemetryStatusResponse(
        degraded=degraded,
        dropped_overflow=dropped_overflow,
        dropped_exhausted=dropped_exhausted,
        dropped_no_session=dropped_no_session,
        dropped_shutdown=dropped_shutdown,
        error_handler_failures=error_handler_failures,
    )


def make_dashboard_app_grid_entry(
    app_key: str = "my_app",
    status: str = "running",
    display_name: str = "My App",
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


def make_event_entry(
    type: str = "state_changed",
    entity_id: str | None = "light.kitchen",
    timestamp: float = 1_700_000_000.0,
    data: dict | None = None,
) -> EventEntry:
    """Build an EventEntry with sensible defaults."""
    return EventEntry(
        type=type,
        entity_id=entity_id,
        timestamp=timestamp,
        data=data or {},
    )


def make_config_response() -> ConfigResponse:
    """Build a ConfigResponse with sensible defaults."""
    return ConfigResponse(
        dev_mode=False,
        base_url="http://homeassistant.local:8123",
        asyncio_debug_mode=False,
        allow_reload_in_prod=False,
        data_dir="/home/user/.local/share/hassette",
        config_dir="/home/user/.config/hassette",
        web_api=WebApiConfigResponse(
            run=True,
            run_ui=True,
            ui_hot_reload=False,
            host="0.0.0.0",
            port=8126,
            cors_origins=[],
            event_buffer_size=100,
            log_buffer_size=500,
            job_history_size=100,
        ),
        logging=LoggingConfigResponse(log_level="INFO", web_api="WARNING"),
        lifecycle=LifecycleConfigResponse(
            startup_timeout_seconds=30,
            app_startup_timeout_seconds=10,
            app_shutdown_timeout_seconds=10,
        ),
        apps=AppsConfigResponse(autodetect=True, directory="apps"),
        scheduler=SchedulerConfigResponse(
            min_delay_seconds=0,
            max_delay_seconds=3600,
            default_delay_seconds=0,
        ),
        file_watcher=FileWatcherConfigResponse(watch_files=True, debounce_milliseconds=500),
    )


def make_app_health_response(
    error_rate: float = 0.0,
    error_rate_class: str = "good",
    handler_avg_duration: float = 5.0,
    job_avg_duration: float = 10.0,
    last_activity_ts: float | None = 1_700_000_000.0,
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


def make_activity_feed_entry(
    row_id: str = "h-1",
    status: InvocationStatus = InvocationStatus.SUCCESS,
    timestamp: float = 1_700_000_000.0,
    app_key: str = "my_app",
    handler_name: str = "on_state_change",
    duration_ms: float | None = 12.5,
    error_type: str | None = None,
    kind: str = "handler",
) -> ActivityFeedEntry:
    """Build an ActivityFeedEntry with sensible defaults."""
    return ActivityFeedEntry(
        row_id=row_id,
        status=status,
        timestamp=timestamp,
        app_key=app_key,
        handler_name=handler_name,
        duration_ms=duration_ms,
        error_type=error_type,
        kind=kind,  # pyright: ignore[reportArgumentType]
    )


def make_app_config_response(
    app_key: str = "my_app",
    filename: str = "my_app.py",
    class_name: str = "MyApp",
    enabled: bool = True,
    app_config: dict | None = None,
    config_schema: dict | None = None,
) -> AppConfigResponse:
    """Build an AppConfigResponse with sensible defaults."""
    return AppConfigResponse(
        app_key=app_key,
        filename=filename,
        class_name=class_name,
        enabled=enabled,
        app_config=app_config or {"setting_name": "default"},
        config_schema=config_schema,
    )


def make_app_source_response(
    app_key: str = "my_app",
    filename: str = "my_app.py",
    content: str = "class MyApp:\n    pass\n",
    line_count: int = 2,
) -> AppSourceResponse:
    """Build an AppSourceResponse with sensible defaults."""
    return AppSourceResponse(
        app_key=app_key,
        filename=filename,
        content=content,
        line_count=line_count,
    )
