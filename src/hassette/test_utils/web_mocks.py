"""Reusable factories for web/API test stubs (Hassette, RuntimeQueryService, FastAPI app).

These build MagicMock-based stubs for testing HTTP endpoints, HTML responses,
and WebSocket frames — as opposed to ``HassetteHarness`` which wires real
components for integration tests (bus routing, scheduler, state propagation).
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hassette.config.models import DEFAULT_WEB_API_PORT
from hassette.core.runtime_query_service import RuntimeQueryService
from hassette.core.telemetry.query_service import AppHealthAggregates
from hassette.schemas.app_snapshots import AppManifestInfo, AppStatusSnapshot
from hassette.test_utils.web_helpers import make_full_snapshot
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app

TEST_START_EPOCH = 1704067200.0


def wire_telemetry_stubs(hassette: MagicMock) -> None:
    """Wire empty-return async stubs for all TelemetryQueryService methods."""
    ts = hassette._telemetry_query_service
    ts.get_listener_summary = AsyncMock(return_value=[])
    ts.get_job_summary = AsyncMock(return_value=[])
    ts.get_app_health_aggregates = AsyncMock(
        return_value=AppHealthAggregates(
            total_invocations=0,
            handler_errors=0,
            handler_timed_out=0,
            handler_avg_duration_ms=0.0,
            total_executions=0,
            job_errors=0,
            job_timed_out=0,
            job_avg_duration_ms=0.0,
            last_activity_ts=None,
        )
    )
    ts.get_all_app_summaries = AsyncMock(return_value={})
    ts.get_executions = AsyncMock(return_value=[])
    ts.get_slow_handlers = AsyncMock(return_value=[])
    ts.get_session_list = AsyncMock(return_value=[])
    ts.check_health = AsyncMock(return_value=None)
    ts.get_per_app_activity_buckets = AsyncMock(return_value={})
    ts.get_per_app_last_errors = AsyncMock(return_value={})
    ts.get_recent_invocations_1h_all_apps = AsyncMock(return_value={})
    ts.get_app_recent_activity = AsyncMock(return_value=[])
    ts.get_log_records = AsyncMock(return_value=[])
    ts.get_log_records_by_execution = AsyncMock(return_value=([], False))
    ts.check_execution_predates_retention_cutoff = AsyncMock(return_value=False)
    hassette.telemetry_query_service = ts


def create_hassette_stub(
    *,
    # Config
    run_web_api: bool = True,
    run_web_ui: bool = True,
    cors_origins: tuple[str, ...] = ("http://localhost:3000",),
    log_level: str = "INFO",
    dev_mode: bool = True,
    allow_reload_in_prod: bool = False,
    # State
    states: dict[str, dict[str, Any]] | None = None,
    is_ready: bool = True,
    # Apps
    manifests: list[AppManifestInfo] | None = None,
    old_snapshot: AppStatusSnapshot | None = None,
    app_action_mocks: bool = False,
    # Scheduler
    scheduler_jobs: list[Any] | None = None,
) -> MagicMock:
    """Build a fully-wired MagicMock Hassette stub for web/API test fixtures.

    All ``hassette.<public> = hassette._<private>`` wiring, state proxy
    side effects, and snapshot plumbing is handled automatically.
    """
    hassette = MagicMock()

    # Matches a real fresh Hassette (no fatal reason yet) so code branching on
    # `fatal_shutdown_reason is not None` sees None, not MagicMock's auto-truthy attribute.
    hassette._fatal_shutdown_reason = None
    hassette.fatal_shutdown_reason = None

    # Root-level fields
    hassette.config.dev_mode = dev_mode
    hassette.config.base_url = "http://127.0.0.1:8123"
    hassette.config.asyncio_debug_mode = False
    hassette.config.allow_reload_in_prod = allow_reload_in_prod
    hassette.config.data_dir = "/srv/hassette/data"
    hassette.config.config_dir = "/srv/hassette/config"
    # web_api group
    hassette.config.web_api.run = run_web_api
    hassette.config.web_api.run_ui = run_web_ui
    hassette.config.web_api.ui_hot_reload = False
    hassette.config.web_api.host = "0.0.0.0"
    hassette.config.web_api.port = DEFAULT_WEB_API_PORT
    hassette.config.web_api.cors_origins = cors_origins
    hassette.config.web_api.log_buffer_size = 2000
    hassette.config.web_api.job_history_size = 1000
    # logging group
    hassette.config.logging.log_level = log_level
    hassette.config.logging.web_api = log_level
    # lifecycle group
    hassette.config.lifecycle.startup_timeout_seconds = 30
    hassette.config.lifecycle.app_startup_timeout_seconds = 20
    hassette.config.lifecycle.app_shutdown_timeout_seconds = 10
    # app group
    hassette.config.apps.autodetect = True
    hassette.config.apps.directory = "/srv/hassette/apps"
    # scheduler group
    hassette.config.scheduler.min_delay_seconds = 1
    hassette.config.scheduler.max_delay_seconds = 30
    hassette.config.scheduler.default_delay_seconds = 15
    # file_watcher group
    hassette.config.file_watcher.watch_files = True
    hassette.config.file_watcher.debounce_milliseconds = 3000

    # model_dump return value — mirrors the attribute assignments above so the config
    # endpoint (which calls hassette.config.model_dump(mode="json")) receives a real dict
    # rather than a MagicMock.  Per-test attribute overrides on hassette.config.* won't
    # automatically reflect here; tests that need specific serialised values should update
    # model_dump.return_value directly or use a real HassetteConfig fixture.
    hassette.config.model_dump.return_value = {
        "dev_mode": dev_mode,
        "base_url": "http://127.0.0.1:8123",
        "asyncio_debug_mode": False,
        "allow_reload_in_prod": allow_reload_in_prod,
        "token": None,
        "data_dir": "/srv/hassette/data",
        "config_dir": "/srv/hassette/config",
        "web_api": {
            "run": run_web_api,
            "run_ui": run_web_ui,
            "ui_hot_reload": False,
            "host": "0.0.0.0",
            "port": DEFAULT_WEB_API_PORT,
            "cors_origins": list(cors_origins),
            "log_buffer_size": 2000,
            "job_history_size": 1000,
        },
        "logging": {"log_level": log_level, "web_api": log_level},
        "lifecycle": {
            "startup_timeout_seconds": 30,
            "app_startup_timeout_seconds": 20,
            "app_shutdown_timeout_seconds": 10,
        },
        "apps": {"autodetect": True, "directory": "/srv/hassette/apps"},
        "scheduler": {"min_delay_seconds": 1, "max_delay_seconds": 30, "default_delay_seconds": 15},
        "file_watcher": {"watch_files": True, "debounce_milliseconds": 3000},
        "database": {"retention_days": 7},
        "websocket": {},
        "blocking_io": {},
    }

    hassette.state_proxy = hassette._state_proxy
    hassette._state_proxy.states = states if states is not None else {}
    hassette._state_proxy.get_state.side_effect = lambda eid: hassette._state_proxy.states.get(eid)
    hassette._state_proxy.get_domain_states.side_effect = lambda domain: {
        eid: s for eid, s in hassette._state_proxy.states.items() if eid.startswith(f"{domain}.")
    }
    hassette._state_proxy.is_ready.return_value = is_ready

    hassette.websocket_service = hassette._websocket_service
    hassette._websocket_service._status = ResourceStatus.RUNNING
    hassette._websocket_service.is_ready.return_value = is_ready
    hassette._websocket_service.ever_connected = is_ready

    hassette.app_handler = hassette._app_handler

    # New-style manifest snapshot
    snapshot = make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot

    # App status snapshot (AppStatusSnapshot domain object)
    if old_snapshot is None:
        old_snapshot = AppStatusSnapshot(running=[], failed=[])
    hassette._app_handler.get_status_snapshot.return_value = old_snapshot

    if app_action_mocks:
        hassette._app_handler.start_app = AsyncMock()
        hassette._app_handler.stop_app = AsyncMock()
        hassette._app_handler.reload_app = AsyncMock()

    hassette.bus_service = hassette._bus_service
    hassette.bus_service.live_execution_counts = MagicMock(return_value={})

    hassette.scheduler_service = hassette._scheduler_service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=scheduler_jobs or [])

    hassette.runtime_query_service = hassette._runtime_query_service

    hassette.database_service = hassette._database_service
    hassette._database_service.submit = AsyncMock(return_value=[])

    wire_telemetry_stubs(hassette)

    hassette.get_drop_counters.return_value = (0, 0, 0)

    hassette.children = []

    return hassette


def create_mock_runtime_query_service(
    mock_hassette: MagicMock,
    *,
    start_time: float = TEST_START_EPOCH,
    use_real_lock: bool = True,
) -> RuntimeQueryService:
    """Build a RuntimeQueryService wired to the given mock Hassette.

    Args:
        mock_hassette: The mock Hassette instance to wire into.
        start_time: Epoch timestamp for uptime calculations.
        use_real_lock: If True, use ``asyncio.Lock()`` (requires a running
            event loop on Python 3.12+).  Set to False for session-scoped
            fixtures where no loop is active yet.
    """
    svc = RuntimeQueryService.__new__(RuntimeQueryService)
    svc.hassette = mock_hassette
    svc._ws_clients = set()
    svc._lock = asyncio.Lock() if use_real_lock else MagicMock()
    svc._start_time = start_time
    svc._subscriptions = []
    svc._ws_drops = 0
    svc._ws_drops_since_last_log = 0
    svc._ws_drops_last_logged = 0.0
    svc._pending_completions = []
    svc._flush_scheduled = False
    svc.task_bucket = MagicMock()
    svc.task_bucket.spawn = MagicMock(side_effect=lambda coro, **_kw: coro.close())
    svc.logger = MagicMock()
    mock_hassette._runtime_query_service = svc
    mock_hassette.runtime_query_service = svc
    return svc


def create_test_fastapi_app(
    mock_hassette: MagicMock,
    *,
    log_handler: Any | None = None,
) -> Any:
    """Build a FastAPI app from the mock Hassette, optionally wiring a log handler.

    If ``log_handler`` is provided, it is set as the capture handler on the mock
    Hassette's logging_service so RuntimeQueryService can reach it via
    ``hassette.logging_service.capture_handler``.

    Returns:
        The FastAPI application instance.
    """
    if log_handler is not None:
        mock_hassette.logging_service.capture_handler = log_handler
    return create_fastapi_app(mock_hassette)
