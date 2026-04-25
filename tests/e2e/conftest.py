"""Fixtures for Playwright-based e2e tests of the Hassette Web UI."""

import logging
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import uvicorn

from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app
from tests.e2e.mock_fixtures import (
    build_error_records,
    build_global_summaries,
    build_handler_invocations,
    build_job_executions,
    build_job_telemetry,
    build_listener_telemetry,
    build_manifests,
    build_old_snapshot,
    build_scheduler_jobs,
    build_session_list,
    wire_app_health_summaries,
    wire_error_telemetry,
    wire_global_summary,
    wire_invocation_telemetry,
    wire_job_telemetry,
    wire_listener_telemetry,
    wire_owner_resolution,
    wire_session_telemetry,
)

# Shared viewport constants for e2e tests.
# Mobile height 812 = iPhone X (safe-area / notch testing).
# Desktop 1024x768 = standard desktop above mobile breakpoint.
MOBILE_VIEWPORT = {"width": 375, "height": 812}
DESKTOP_VIEWPORT = {"width": 1024, "height": 768}


@pytest.fixture(scope="session")
def mock_hassette():
    """Create a session-scoped mock Hassette with rich seed data."""
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
        manifests=build_manifests(),
        old_snapshot=build_old_snapshot(),
        scheduler_jobs=build_scheduler_jobs(),
    )

    # Wire telemetry seed data.
    wire_listener_telemetry(hassette, build_listener_telemetry())
    wire_job_telemetry(hassette, build_job_telemetry())
    wire_invocation_telemetry(hassette, build_handler_invocations(), build_job_executions())
    wire_app_health_summaries(hassette)
    wire_session_telemetry(hassette, build_session_list())

    app_tier_errors, framework_tier_errors = build_error_records()
    wire_error_telemetry(hassette, app_tier_errors, framework_tier_errors)

    framework_summary, default_summary = build_global_summaries()
    wire_global_summary(hassette, framework_summary, default_summary)

    # Session ID for error feed session scoping.
    hassette.session_id = 1

    # Owner resolution wiring.
    wire_owner_resolution(hassette)

    hassette.telemetry_query_service = hassette._telemetry_query_service

    return hassette


@pytest.fixture(scope="session")
def runtime_query_service(mock_hassette):
    """Create a session-scoped RuntimeQueryService wired to mock_hassette."""
    return create_mock_runtime_query_service(mock_hassette, use_real_lock=False)


@pytest.fixture(scope="session")
def _log_handler():
    """Create a LogCaptureHandler with seed log entries for e2e tests."""
    handler = LogCaptureHandler(buffer_size=100)
    handler.register_app_logger("hassette.apps.my_app", "my_app")
    entries = [
        ("hassette.core", logging.INFO, "Hassette started successfully"),
        ("hassette.apps.my_app", logging.INFO, "MyApp initialized"),
        ("hassette.apps.my_app", logging.WARNING, "Light kitchen unresponsive"),
        ("hassette.core", logging.DEBUG, "WebSocket heartbeat sent"),
        ("hassette.apps.my_app", logging.ERROR, "Failed to call service"),
        (
            "hassette.apps.my_app",
            logging.INFO,
            "Processing state change for sensor.living_room_temperature with attributes: "
            "unit_of_measurement=°C, friendly_name=Living Room Temperature, device_class=temperature, "
            "state_class=measurement, last_reset=2024-01-01T00:00:00+00:00",
        ),
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


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SPA_INDEX = _REPO_ROOT / "src" / "hassette" / "web" / "static" / "spa" / "index.html"


@pytest.fixture(scope="session")
def _ensure_spa_built():
    """Build the frontend SPA if the build output is missing."""
    if _SPA_INDEX.exists():
        return
    frontend_dir = _REPO_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        pytest.skip("frontend/ directory not found — cannot build SPA for e2e tests")
    if not shutil.which("npm"):
        pytest.skip("npm not found — cannot build SPA for e2e tests")
    subprocess.run(["npm", "ci", "--prefix", str(frontend_dir)], check=True)
    subprocess.run(["npm", "run", "build", "--prefix", str(frontend_dir)], check=True)
    if not _SPA_INDEX.exists():
        pytest.fail("Frontend build completed but spa/index.html not found")


@pytest.fixture(scope="session")
def _fastapi_app(mock_hassette, runtime_query_service, _log_handler, _ensure_spa_built):  # noqa: ARG001
    """Create the FastAPI app instance."""

    with patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=_log_handler):
        app = create_fastapi_app(mock_hassette)
    # Patch persistently so runtime calls also find the handler
    patcher = patch("hassette.core.runtime_query_service.get_log_capture_handler", return_value=_log_handler)
    patcher.start()
    yield app
    patcher.stop()


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

    # Poll until the server is accepting connections.
    # socket.create_connection(..., timeout=0.5) already blocks for up to 0.5s per
    # attempt, so no additional sleep is needed between retries.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"Live server did not start within 10s on port {port}")

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("Live server did not stop within 5s")


@pytest.fixture(scope="session")
def base_url(live_server: str) -> str:
    """Override pytest-playwright's base_url fixture."""
    return live_server


@pytest.fixture(autouse=True)
def _default_scope_all(page, base_url: str) -> None:
    """Set session scope to 'all' so telemetry loads without a WS-provided sessionId.

    The E2E test server disables WebSocket (ws='none'), so the frontend
    never receives a sessionId. With scope='current' (the user-facing
    default), useScopedApi returns a loading state. Setting scope to
    'all' lets all existing tests see real data.

    Individual tests can override by setting localStorage themselves.
    """
    page.goto(base_url + "/")
    page.evaluate('localStorage.setItem("hassette:sessionScope", JSON.stringify("all"))')
    page.reload()
