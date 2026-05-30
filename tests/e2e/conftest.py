"""Fixtures for Playwright-based e2e tests of the Hassette Web UI."""

import asyncio
import logging
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import uvicorn

from hassette.logging_ import LogCaptureHandler, LogEntry
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.web.app import create_fastapi_app
from tests.e2e.mock_fixtures import (
    build_app_health_summaries,
    build_error_records,
    build_executions,
    build_global_summaries,
    build_job_telemetry,
    build_listener_telemetry,
    build_manifests,
    build_old_snapshot,
    build_scheduler_jobs,
    build_session_list,
    wire_app_health_summaries,
    wire_app_manifest_lookups,
    wire_config,
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
SMALL_MOBILE_VIEWPORT = {"width": 320, "height": 480}
MOBILE_BOUNDARY_VIEWPORT = {"width": 768, "height": 1024}
NARROW_DESKTOP_VIEWPORT = {"width": 800, "height": 600}
DESKTOP_VIEWPORT = {"width": 1024, "height": 768}

ANIMATION_SETTLE_MS = 300
DATA_LOAD_TIMEOUT_MS = 5000


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
    wire_invocation_telemetry(hassette, build_executions())
    wire_app_health_summaries(hassette, build_app_health_summaries())
    wire_session_telemetry(hassette, build_session_list())

    app_tier_errors, framework_tier_errors = build_error_records()
    wire_error_telemetry(hassette, app_tier_errors, framework_tier_errors)

    framework_summary, default_summary = build_global_summaries()
    wire_global_summary(hassette, framework_summary, default_summary)

    # Owner resolution wiring.
    wire_owner_resolution(hassette)

    # Wire manifest lookups for /apps/{key}/config and /apps/{key}/source endpoints.
    wire_app_manifest_lookups(hassette, build_manifests())

    # Wire realistic config stub so GET /config returns valid data.
    wire_config(hassette)

    hassette.telemetry_query_service = hassette._telemetry_query_service

    return hassette


@pytest.fixture(scope="session")
def runtime_query_service(mock_hassette):
    """Create a session-scoped RuntimeQueryService wired to mock_hassette."""
    return create_mock_runtime_query_service(mock_hassette, use_real_lock=False)


@pytest.fixture(scope="session")
def log_handler():
    """Create a LogCaptureHandler with seed log entries for e2e tests."""
    handler = LogCaptureHandler(buffer_size=100)
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
        prefix = "hassette.apps."
        if logger_name.startswith(prefix):
            record.app_key = logger_name[len(prefix) :].split(".")[0]
            record.source_tier = "app"
        else:
            record.source_tier = "framework"
        handler.emit(record)
    return handler


_REPO_ROOT = Path(__file__).resolve().parents[2]
SPA_INDEX = _REPO_ROOT / "src" / "hassette" / "web" / "static" / "spa" / "index.html"


@pytest.fixture(scope="session")
def ensure_spa_built():
    """Build the frontend SPA if the build output is missing."""
    if SPA_INDEX.exists():
        return
    frontend_dir = _REPO_ROOT / "frontend"
    if not (frontend_dir / "package.json").exists():
        pytest.skip("frontend/ directory not found — cannot build SPA for e2e tests")
    if not shutil.which("npm"):
        pytest.skip("npm not found — cannot build SPA for e2e tests")
    subprocess.run(["npm", "ci", "--prefix", str(frontend_dir)], check=True)
    subprocess.run(["npm", "run", "build", "--prefix", str(frontend_dir)], check=True)
    if not SPA_INDEX.exists():
        pytest.fail("Frontend build completed but spa/index.html not found")


def make_log_records_from_buffer(handler: LogCaptureHandler):
    """Return an async function that serves log records from the capture handler buffer.

    Replaces ``TelemetryQueryService.get_log_records`` in E2E tests so the seeded
    LogCaptureHandler data is returned by the REST API (which queries the DB
    in production, but we don't run a real DB in E2E).

    Filter semantics must match the SQL in ``TelemetryQueryService.get_log_records()``
    (exact equality per column, not range-based).
    """

    async def _get_log_records(
        *,
        limit: int = 100,
        since: float | None = None,
        app_key: str | None = None,
        level: str | None = None,
        execution_id: str | None = None,
        source_tier: str | None = None,
    ) -> list[dict]:
        entries: list[LogEntry] = handler.get_buffer_snapshot()
        result = [e.to_dict() for e in entries]
        if since is not None:
            result = [r for r in result if r["timestamp"] >= since]
        if app_key is not None:
            result = [r for r in result if r.get("app_key") == app_key]
        if level is not None:
            result = [r for r in result if r.get("level") == level]
        if execution_id is not None:
            result = [r for r in result if r.get("execution_id") == execution_id]
        if source_tier is not None:
            result = [r for r in result if r.get("source_tier") == source_tier]
        result.sort(key=lambda r: r["timestamp"], reverse=True)
        return result[:limit]

    return _get_log_records


@pytest.fixture(scope="session")
def fastapi_app(mock_hassette, runtime_query_service, log_handler, ensure_spa_built):  # noqa: ARG001
    """Create the FastAPI app instance."""

    mock_hassette.telemetry_query_service.get_log_records = make_log_records_from_buffer(log_handler)

    # Wire log_handler as the capture_handler on the mock logging_service so
    # RuntimeQueryService.on_initialize() can reach it via hassette.logging_service.capture_handler.
    mock_hassette.logging_service.capture_handler = log_handler

    return create_fastapi_app(mock_hassette)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(fastapi_app):
    """Start a real uvicorn server in a daemon thread and yield its base URL."""
    port = get_free_port()
    # Disable WS protocol to avoid websockets.legacy DeprecationWarning (which
    # becomes an error under pytest's filterwarnings=["error"] setting).
    config = uvicorn.Config(app=fastapi_app, host="127.0.0.1", port=port, log_level="warning", ws="none")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Poll until the server is accepting connections.
    # socket.create_connection blocks up to 0.5s on success; the short sleep
    # prevents a tight spin on connection-refused (which returns instantly).
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
def set_time_preset_to_1h(request: pytest.FixtureRequest, page, base_url: str) -> None:
    """Force timePreset='1h' in localStorage before every test page load.

    The new UI uses useScopedApi which gates fetches on uptimeSeconds received
    from the WebSocket connected message.  When ws='none' (the default test
    server), the WS never connects and uptimeSeconds stays null, so the default
    preset "since-restart" permanently blocks all scoped API calls and app detail
    pages never finish loading.

    Switching to the "1h" preset unblocks useScopedApi: resolveSince("1h", null)
    returns Date.now()/1000 - 3600, which is a valid timestamp regardless of WS.

    Tests that use live_server_ws explicitly exercise the WS path and must NOT
    have the preset forced — they receive uptimeSeconds from the real WS
    connected message and test the "since-restart" gate.

    Strategy: navigate to the app's origin first (to establish the right
    localStorage origin), set the key, then let the test navigate freely.
    The SPA reads timePreset from localStorage on each mount, so any subsequent
    page.goto() will see the pre-set value.
    """
    if "live_server_ws" in request.fixturenames or "live_server_ws_inject" in request.fixturenames:
        return
    # Navigate to the origin to establish correct localStorage scope, then seed
    # the timePreset key so useScopedApi is unblocked from the first render.
    page.goto(base_url + "/")
    page.evaluate("localStorage.setItem('hassette:timePreset', JSON.stringify('1h'));")


# ── WebSocket-enabled server fixtures ─────────────────────────────────
#
# Two server configurations serve different testing needs:
#
#  live_server (session-scoped, ws='none') — used by almost all E2E tests.
#    WebSocket is disabled to avoid the websockets.legacy DeprecationWarning
#    that becomes a hard error under pytest's filterwarnings=["error"].
#    The _default_scope_all autouse fixture forces sessionScope='all' so
#    telemetry loads without a WS-provided sessionId.
#
#  live_server_ws (function-scoped, ws='websockets-sansio') — used only by
#    tests that need to exercise the WebSocket session path (scope='current'
#    + session ID). websockets-sansio avoids the legacy DeprecationWarning.
#    Tests using this fixture receive the session_id from the real WS
#    connected message — nothing is mocked.


@pytest.fixture
def live_server_ws(fastapi_app, runtime_query_service):
    """Start a WebSocket-enabled uvicorn server for session-path tests.

    Uses ws='websockets-sansio' to avoid the websockets.legacy DeprecationWarning
    that is promoted to an error by pytest's filterwarnings=["error"] setting.
    Function-scoped: the server starts and stops per test to keep WS tests isolated.

    The session-scoped runtime_query_service was created with use_real_lock=False
    (a MagicMock for _lock) because asyncio.Lock was loop-bound in older Pythons.
    Since Python 3.10+, Lock picks up the running loop on first use, so we can
    safely replace the mock with a real Lock here for the duration of this fixture.
    The original mock is restored after the test to avoid cross-test contamination.
    """
    # Swap in a real asyncio.Lock so register_ws_client / unregister_ws_client work.
    original_lock = runtime_query_service._lock
    runtime_query_service._lock = asyncio.Lock()

    port = get_free_port()
    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets-sansio",
        # Short graceful shutdown: browser WebSocket stays open until Playwright
        # releases it, so we cannot wait forever. Cancel lingering connections
        # after 1 second and proceed. The daemon thread ensures the process
        # does not hang if the server does not exit cleanly.
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"WS-enabled live server did not start within 10s on port {port}")

    yield f"http://127.0.0.1:{port}"

    try:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("WS-enabled live server did not stop within 5s")
    finally:
        runtime_query_service._lock = original_lock


@pytest.fixture
def live_server_ws_inject(fastapi_app, runtime_query_service):
    """WebSocket-enabled server that exposes a sync broadcast helper for injection tests.

    Extends the live_server_ws pattern with a ``broadcast_sync(msg)`` callable
    that pushes an arbitrary dict to all connected WS clients from the test thread.
    The server's asyncio event loop is captured from inside the thread via a
    threading.Event + captured reference, set just before uvicorn starts serving.

    Yields a ``SimpleNamespace`` with:
    - ``url``  — base URL string (e.g. ``http://127.0.0.1:<port>``)
    - ``broadcast_sync(msg)``  — synchronously pushes ``msg`` to WS clients
    """
    original_lock = runtime_query_service._lock
    runtime_query_service._lock = asyncio.Lock()

    port = get_free_port()
    config = uvicorn.Config(
        app=fastapi_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets-sansio",
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)

    # Capture the server's event loop from inside the thread before uvicorn begins
    # serving. We patch server.startup to grab asyncio.get_running_loop() once the
    # server is up and signal the main thread via an Event.
    loop_ready = threading.Event()
    _captured: list[asyncio.AbstractEventLoop] = []

    _original_startup = server.startup

    async def _startup_and_capture(sockets=None):
        await _original_startup(sockets=sockets)
        _captured.append(asyncio.get_running_loop())
        loop_ready.set()

    server.startup = _startup_and_capture

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to accept connections.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError(f"WS-inject server did not start within 10s on port {port}")

    # Wait for the loop capture to be signalled.
    if not loop_ready.wait(timeout=5):
        raise RuntimeError("uvicorn server loop did not become available within 5s")
    loop = _captured[0]

    def broadcast_sync(msg: dict) -> None:
        """Push msg to all connected WS clients synchronously from the test thread."""
        future = asyncio.run_coroutine_threadsafe(runtime_query_service.broadcast(msg), loop)
        future.result(timeout=5)

    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", broadcast_sync=broadcast_sync)

    try:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("WS-inject server did not stop within 5s")
    finally:
        runtime_query_service._lock = original_lock
