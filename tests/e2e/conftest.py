"""Fixtures for Playwright-based e2e tests of the Hassette Web UI."""

import logging
import socket
import threading
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import uvicorn

from hassette.core.app_registry import AppFullSnapshot, AppInstanceInfo, AppManifestInfo
from hassette.core.data_sync_service import DataSyncService
from hassette.logging_ import LogCaptureHandler
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app


def _make_full_snapshot(
    manifests: list[AppManifestInfo] | None = None,
    only_app: str | None = None,
) -> AppFullSnapshot:
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


def _make_manifest(
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
) -> AppManifestInfo:
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
    )


def _build_manifests() -> list[AppManifestInfo]:
    """Build a rich set of app manifests for e2e tests."""
    return [
        _make_manifest(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            status="running",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="my_app",
                    index=0,
                    instance_name="MyApp[0]",
                    class_name="MyApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MyApp.MyApp[0]",
                )
            ],
        ),
        _make_manifest(
            app_key="other_app",
            class_name="OtherApp",
            display_name="Other App",
            filename="other_app.py",
            status="stopped",
            instance_count=0,
        ),
        _make_manifest(
            app_key="broken_app",
            class_name="BrokenApp",
            display_name="Broken App",
            filename="broken_app.py",
            status="failed",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="broken_app",
                    index=0,
                    instance_name="BrokenApp[0]",
                    class_name="BrokenApp",
                    status=ResourceStatus.FAILED,
                    error_message="Init error: bad config",
                )
            ],
            error_message="Init error: bad config",
        ),
        _make_manifest(
            app_key="disabled_app",
            class_name="DisabledApp",
            display_name="Disabled App",
            filename="disabled_app.py",
            enabled=False,
            status="disabled",
            instance_count=0,
        ),
    ]


def _make_listener_metric(
    listener_id: int,
    owner: str,
    topic: str,
    handler_name: str,
    invocations: int = 10,
    successful: int = 9,
    failed: int = 1,
) -> MagicMock:
    d = {
        "listener_id": listener_id,
        "owner": owner,
        "topic": topic,
        "handler_name": handler_name,
        "total_invocations": invocations,
        "successful": successful,
        "failed": failed,
        "di_failures": 0,
        "cancelled": 0,
        "total_duration_ms": invocations * 2.0,
        "min_duration_ms": 1.0,
        "max_duration_ms": 5.0,
        "avg_duration_ms": 2.0,
        "last_invoked_at": None,
        "last_error_message": None,
        "last_error_type": None,
    }
    m = MagicMock()
    m.to_dict.return_value = d
    # Expose attributes directly for bus_metrics_summary
    for k, v in d.items():
        setattr(m, k, v)
    return m


@pytest.fixture(scope="session")
def mock_hassette():
    """Create a session-scoped mock Hassette with rich seed data."""
    hassette = MagicMock()
    hassette.config.run_web_api = True
    hassette.config.run_web_ui = True
    hassette.config.web_api_cors_origins = ("http://localhost:3000",)
    hassette.config.web_api_event_buffer_size = 100
    hassette.config.web_api_log_level = "INFO"
    hassette.config.dev_mode = True
    hassette.config.allow_reload_in_prod = False

    # --- State proxy ---
    hassette.state_proxy = hassette._state_proxy
    hassette._state_proxy.states = {
        "light.kitchen": {
            "entity_id": "light.kitchen",
            "state": "on",
            "attributes": {"brightness": 255, "friendly_name": "Kitchen Light"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
        "light.bedroom": {
            "entity_id": "light.bedroom",
            "state": "off",
            "attributes": {"brightness": 0, "friendly_name": "Bedroom Light"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
        "sensor.temperature": {
            "entity_id": "sensor.temperature",
            "state": "22.5",
            "attributes": {"unit_of_measurement": "°C", "friendly_name": "Temperature"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
        "switch.fan": {
            "entity_id": "switch.fan",
            "state": "on",
            "attributes": {"friendly_name": "Fan"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
        "binary_sensor.door": {
            "entity_id": "binary_sensor.door",
            "state": "off",
            "attributes": {"device_class": "door", "friendly_name": "Front Door"},
            "last_changed": "2024-01-01T00:00:00",
            "last_updated": "2024-01-01T00:00:00",
        },
    }
    hassette._state_proxy.get_state.side_effect = lambda eid: hassette._state_proxy.states.get(eid)
    hassette._state_proxy.get_domain_states.side_effect = lambda domain: {
        eid: s for eid, s in hassette._state_proxy.states.items() if eid.startswith(f"{domain}.")
    }
    hassette._state_proxy.is_ready.return_value = True

    # --- WebSocket service ---
    hassette.websocket_service = hassette._websocket_service
    hassette._websocket_service.status = ResourceStatus.RUNNING

    # --- App handler ---
    hassette.app_handler = hassette._app_handler

    manifests = _build_manifests()
    snapshot = _make_full_snapshot(manifests)
    hassette._app_handler.registry.get_full_snapshot.return_value = snapshot

    # Old-style snapshot for get_app_status_snapshot
    old_snapshot = SimpleNamespace(
        running=[
            SimpleNamespace(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status=SimpleNamespace(value="running"),
                error_message=None,
                owner_id="MyApp.MyApp[0]",
            )
        ],
        failed=[
            SimpleNamespace(
                app_key="broken_app",
                index=0,
                instance_name="BrokenApp[0]",
                class_name="BrokenApp",
                status=SimpleNamespace(value="failed"),
                error_message="Init error: bad config",
                owner_id=None,
            )
        ],
        total_count=2,
        running_count=1,
        failed_count=1,
        only_app=None,
    )
    hassette._app_handler.get_status_snapshot.return_value = old_snapshot

    # --- Owner resolution ---
    app_instances = {
        0: SimpleNamespace(unique_name="MyApp.MyApp[0]"),
    }
    hassette._app_handler.registry.iter_all_instances.return_value = [
        ("my_app", 0, SimpleNamespace(unique_name="MyApp.MyApp[0]")),
    ]
    hassette._app_handler.registry.get_apps_by_key.return_value = app_instances
    hassette._app_handler.registry.get.side_effect = lambda app_key, index=0: (
        SimpleNamespace(unique_name="MyApp.MyApp[0]") if app_key == "my_app" and index == 0 else None
    )

    # --- Bus service ---
    hassette.bus_service = hassette._bus_service
    listener_metrics = [
        _make_listener_metric(1, "MyApp.MyApp[0]", "state_changed.light.kitchen", "on_light_change"),
        _make_listener_metric(2, "MyApp.MyApp[0]", "state_changed.sensor.temperature", "on_temp_update", 20, 20, 0),
    ]
    hassette._bus_service.get_all_listener_metrics.return_value = listener_metrics
    hassette._bus_service.get_listener_metrics_by_owner.side_effect = lambda owner: [
        m for m in listener_metrics if m.to_dict()["owner"] == owner
    ]

    # --- Scheduler service ---
    hassette.scheduler_service = hassette._scheduler_service
    hassette._scheduler_service.get_all_jobs = AsyncMock(
        return_value=[
            SimpleNamespace(
                job_id="job-1",
                name="check_lights",
                owner="MyApp.MyApp[0]",
                next_run="2024-01-01T00:05:00",
                repeat=True,
                cancelled=False,
                trigger=type("interval", (), {})(),
            ),
            SimpleNamespace(
                job_id="job-2",
                name="morning_routine",
                owner="MyApp.MyApp[0]",
                next_run="2024-01-01T07:00:00",
                repeat=True,
                cancelled=False,
                trigger=type("cron", (), {})(),
            ),
        ]
    )
    hassette._scheduler_service.get_execution_history.return_value = []

    # --- Data sync service placeholder ---
    hassette.data_sync_service = hassette._data_sync_service

    # --- Children for system status ---
    hassette.children = []

    return hassette


@pytest.fixture(scope="session")
def data_sync_service(mock_hassette):
    """Create a session-scoped DataSyncService wired to mock_hassette."""
    ds = DataSyncService.__new__(DataSyncService)
    ds.hassette = mock_hassette
    ds._event_buffer = deque(maxlen=100)
    ds._ws_clients = set()
    # Use a MagicMock for the lock — creating asyncio.Lock() outside a running
    # event loop raises DeprecationWarning on 3.12+ (which becomes an error
    # under filterwarnings=["error"]).  The e2e tests never exercise async paths.
    ds._lock = MagicMock()
    ds._start_time = 1704067200.0
    ds._subscriptions = []
    ds.logger = MagicMock()
    mock_hassette._data_sync_service = ds
    mock_hassette.data_sync_service = ds
    return ds


@pytest.fixture(scope="session")
def _log_handler():
    """Create a LogCaptureHandler with seed log entries for e2e tests."""
    handler = LogCaptureHandler(buffer_size=100)
    entries = [
        ("hassette.core", logging.INFO, "Hassette started successfully"),
        ("hassette.apps.my_app", logging.INFO, "MyApp initialized"),
        ("hassette.apps.my_app", logging.WARNING, "Light kitchen unresponsive"),
        ("hassette.core", logging.DEBUG, "WebSocket heartbeat sent"),
        ("hassette.apps.my_app", logging.ERROR, "Failed to call service"),
    ]
    for logger_name, level, msg in entries:
        record = logging.LogRecord(
            name=logger_name,
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        handler.emit(record)
    return handler


@pytest.fixture(scope="session")
def _fastapi_app(mock_hassette, data_sync_service, _log_handler):  # noqa: ARG001
    """Create the FastAPI app instance."""
    with patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=_log_handler):
        app = create_fastapi_app(mock_hassette)
    # Patch persistently so runtime calls also find the handler
    patcher = patch("hassette.core.data_sync_service.get_log_capture_handler", return_value=_log_handler)
    patcher.start()
    return app


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(_fastapi_app):
    """Start a real uvicorn server in a daemon thread and yield its base URL."""
    port = _get_free_port()
    # Disable WS protocol to avoid websockets.legacy DeprecationWarning (which
    # becomes an error under pytest's filterwarnings=["error"] setting).
    config = uvicorn.Config(app=_fastapi_app, host="127.0.0.1", port=port, log_level="warning", ws="none")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until the server is accepting connections
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Live server did not start within 10s on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    """Override pytest-playwright's base_url fixture."""
    return live_server


@pytest.fixture(autouse=True)
def cleanup_state_proxy_fixture():
    """Override the async autouse fixture from hassette.test_utils.fixtures.

    The parent conftest registers an async cleanup_state_proxy_fixture via
    pytest_plugins.  Playwright tests are synchronous, so the async fixture
    causes a coroutine-never-awaited error.  This sync override is a no-op.
    """
