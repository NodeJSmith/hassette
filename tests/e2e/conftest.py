"""Fixtures for Playwright-based e2e tests of the Hassette Web UI."""

import logging
import socket
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import uvicorn

from hassette.core.app_registry import AppInstanceInfo
from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_helpers import (
    make_job,
    make_listener_metric,
    make_manifest,
    make_old_app_instance,
    make_old_snapshot,
)
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_data_sync_service
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app


def _build_manifests() -> list:
    """Build a rich set of app manifests for e2e tests."""
    return [
        make_manifest(
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
        make_manifest(
            app_key="other_app",
            class_name="OtherApp",
            display_name="Other App",
            filename="other_app.py",
            status="stopped",
            instance_count=0,
        ),
        make_manifest(
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
        make_manifest(
            app_key="disabled_app",
            class_name="DisabledApp",
            display_name="Disabled App",
            filename="disabled_app.py",
            enabled=False,
            status="disabled",
            instance_count=0,
        ),
    ]


@pytest.fixture(scope="session")
def mock_hassette():
    """Create a session-scoped mock Hassette with rich seed data."""
    manifests = _build_manifests()
    listener_metrics = [
        make_listener_metric(1, "MyApp.MyApp[0]", "state_changed.light.kitchen", "on_light_change"),
        make_listener_metric(2, "MyApp.MyApp[0]", "state_changed.sensor.temperature", "on_temp_update", 20, 20, 0),
    ]

    hassette = create_hassette_stub(
        states={
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
        },
        manifests=manifests,
        old_snapshot=make_old_snapshot(
            running=[
                make_old_app_instance(owner_id="MyApp.MyApp[0]"),
            ],
            failed=[
                make_old_app_instance(
                    app_key="broken_app",
                    instance_name="BrokenApp[0]",
                    class_name="BrokenApp",
                    status="failed",
                    error_message="Init error: bad config",
                    owner_id=None,
                ),
            ],
        ),
        listener_metrics=listener_metrics,
        scheduler_jobs=[
            make_job(),
            make_job(
                job_id="job-2",
                name="morning_routine",
                next_run="2024-01-01T07:00:00",
                trigger_type="cron",
            ),
        ],
    )

    # --- e2e-specific: owner resolution wiring ---
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

    return hassette


@pytest.fixture(scope="session")
def data_sync_service(mock_hassette):
    """Create a session-scoped DataSyncService wired to mock_hassette."""
    return create_mock_data_sync_service(mock_hassette, use_real_lock=False)


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
