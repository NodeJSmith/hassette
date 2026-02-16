"""Reusable factories for web/API test stubs (Hassette, DataSyncService, FastAPI app).

These build MagicMock-based stubs for testing HTTP endpoints, HTML responses,
and WebSocket frames — as opposed to ``HassetteHarness`` which wires real
components for integration tests (bus routing, scheduler, state propagation).
"""

import asyncio
from collections import deque
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hassette.core.app_registry import AppManifestInfo
from hassette.core.data_sync_service import DataSyncService
from hassette.test_utils.web_helpers import make_full_snapshot
from hassette.types.enums import ResourceStatus


def create_hassette_stub(
    *,
    # Config
    run_web_api: bool = True,
    run_web_ui: bool = True,
    cors_origins: tuple[str, ...] = ("http://localhost:3000",),
    event_buffer_size: int = 100,
    log_level: str = "INFO",
    dev_mode: bool = True,
    allow_reload_in_prod: bool = False,
    # State
    states: dict[str, dict[str, Any]] | None = None,
    is_ready: bool = True,
    # Apps
    manifests: list[AppManifestInfo] | None = None,
    old_snapshot: SimpleNamespace | None = None,
    app_action_mocks: bool = False,
    # Bus
    listener_metrics: list[MagicMock] | None = None,
    # Scheduler
    scheduler_jobs: list[Any] | None = None,
    scheduler_history: list[Any] | None = None,
    # Config endpoint
    config_dump: dict[str, Any] | None = None,
) -> MagicMock:
    """Build a fully-wired MagicMock Hassette stub for web/API test fixtures.

    All ``hassette.<public> = hassette._<private>`` wiring, state proxy
    side effects, and snapshot plumbing is handled automatically.
    """
    hassette = MagicMock()

    # --- Config ---
    hassette.config.run_web_api = run_web_api
    hassette.config.run_web_ui = run_web_ui
    hassette.config.web_api_cors_origins = cors_origins
    hassette.config.web_api_event_buffer_size = event_buffer_size
    hassette.config.web_api_log_level = log_level
    hassette.config.dev_mode = dev_mode
    hassette.config.allow_reload_in_prod = allow_reload_in_prod

    # --- State proxy ---
    hassette.state_proxy = hassette._state_proxy
    hassette._state_proxy.states = states if states is not None else {}
    hassette._state_proxy.get_state.side_effect = lambda eid: hassette._state_proxy.states.get(eid)
    hassette._state_proxy.get_domain_states.side_effect = lambda domain: {
        eid: s for eid, s in hassette._state_proxy.states.items() if eid.startswith(f"{domain}.")
    }
    hassette._state_proxy.is_ready.return_value = is_ready

    # --- WebSocket service ---
    hassette.websocket_service = hassette._websocket_service
    hassette._websocket_service.status = ResourceStatus.RUNNING

    # --- App handler ---
    hassette.app_handler = hassette._app_handler

    # New-style manifest snapshot
    snapshot = make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot

    # Old-style snapshot
    if old_snapshot is None:
        old_snapshot = SimpleNamespace(
            running=[], failed=[], total_count=0, running_count=0, failed_count=0, only_app=None
        )
    hassette._app_handler.get_status_snapshot.return_value = old_snapshot

    if app_action_mocks:
        hassette._app_handler.start_app = AsyncMock()
        hassette._app_handler.stop_app = AsyncMock()
        hassette._app_handler.reload_app = AsyncMock()

    # --- Bus service ---
    hassette.bus_service = hassette._bus_service
    hassette._bus_service.get_all_listener_metrics.return_value = listener_metrics or []
    if listener_metrics:
        hassette._bus_service.get_listener_metrics_by_owner.side_effect = lambda owner: [
            m for m in listener_metrics if m.to_dict()["owner"] == owner
        ]
    else:
        hassette._bus_service.get_listener_metrics_by_owner.return_value = []

    # --- Scheduler service ---
    hassette.scheduler_service = hassette._scheduler_service
    hassette._scheduler_service.get_all_jobs = AsyncMock(return_value=scheduler_jobs or [])
    hassette._scheduler_service.get_execution_history.return_value = scheduler_history or []

    # --- Data sync service placeholder ---
    hassette.data_sync_service = hassette._data_sync_service

    # --- Config endpoint ---
    if config_dump is not None:
        hassette.config.model_dump.return_value = config_dump

    # --- Children for system status ---
    hassette.children = []

    return hassette


def create_mock_data_sync_service(
    mock_hassette: MagicMock,
    *,
    buffer_size: int = 100,
    start_time: float = 1704067200.0,
    use_real_lock: bool = True,
) -> DataSyncService:
    """Build a DataSyncService wired to the given mock Hassette.

    Args:
        mock_hassette: The mock Hassette instance to wire into.
        buffer_size: Max size of the event buffer deque.
        start_time: Epoch timestamp for uptime calculations.
        use_real_lock: If True, use ``asyncio.Lock()`` (requires a running
            event loop on Python 3.12+).  Set to False for session-scoped
            fixtures where no loop is active yet.
    """
    ds = DataSyncService.__new__(DataSyncService)
    ds.hassette = mock_hassette
    ds._event_buffer = deque(maxlen=buffer_size)
    ds._ws_clients = set()
    ds._lock = asyncio.Lock() if use_real_lock else MagicMock()
    ds._start_time = start_time
    ds._subscriptions = []
    ds.logger = MagicMock()
    mock_hassette._data_sync_service = ds
    mock_hassette.data_sync_service = ds
    return ds


def create_test_fastapi_app(
    mock_hassette: MagicMock,
    *,
    log_handler: Any | None = None,
) -> Any:
    """Build a FastAPI app from the mock Hassette, optionally patching the log handler.

    Returns:
        The FastAPI application instance.
    """
    from unittest.mock import patch

    from hassette.web.app import create_fastapi_app

    if log_handler is not None:
        with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=log_handler):
            return create_fastapi_app(mock_hassette)
    return create_fastapi_app(mock_hassette)
