"""Fixtures for Playwright-based e2e tests of the Hassette Web UI."""

import logging
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import uvicorn

from hassette.core.app_registry import AppInstanceInfo, AppStatusSnapshot
from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerErrorRecord,
    HandlerInvocation,
    JobErrorRecord,
    JobExecution,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
    ListenerSummary,
    SessionRecord,
)
from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_helpers import (
    make_job,
    make_manifest,
)
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
from hassette.types.enums import ResourceStatus
from hassette.web.app import create_fastapi_app

# Shared viewport constants for e2e tests.
# Mobile height 812 = iPhone X (safe-area / notch testing).
# Desktop 1024x768 = standard desktop above mobile breakpoint.
MOBILE_VIEWPORT = {"width": 375, "height": 812}
DESKTOP_VIEWPORT = {"width": 1024, "height": 768}


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
                    error_traceback=(
                        'Traceback (most recent call last):\n  File "broken_app.py", line 10, in '
                        'on_initialize\n    raise ValueError("bad config")\nValueError: bad config\n'
                    ),
                )
            ],
            error_message="Init error: bad config",
            error_traceback=(
                'Traceback (most recent call last):\n  File "broken_app.py", line 10, in on_initialize\n'
                '    raise ValueError("bad config")\nValueError: bad config\n'
            ),
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
        make_manifest(
            app_key="nosource_app",
            class_name="NoSourceApp",
            display_name="No Source App",
            filename="nosource_app.py",
            status="running",
            instance_count=1,
            instances=[
                AppInstanceInfo(
                    app_key="nosource_app",
                    index=0,
                    instance_name="NoSourceApp[0]",
                    class_name="NoSourceApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="NoSourceApp.NoSourceApp[0]",
                ),
            ],
        ),
        make_manifest(
            app_key="multi_app",
            class_name="MultiApp",
            display_name="Multi App",
            filename="multi_app.py",
            status="running",
            instance_count=3,
            instances=[
                AppInstanceInfo(
                    app_key="multi_app",
                    index=0,
                    instance_name="MultiApp[0]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[0]",
                ),
                AppInstanceInfo(
                    app_key="multi_app",
                    index=1,
                    instance_name="MultiApp[1]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[1]",
                ),
                AppInstanceInfo(
                    app_key="multi_app",
                    index=2,
                    instance_name="MultiApp[2]",
                    class_name="MultiApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MultiApp.MultiApp[2]",
                ),
            ],
        ),
    ]


@pytest.fixture(scope="session")
def mock_hassette():
    """Create a session-scoped mock Hassette with rich seed data."""
    manifests = _build_manifests()

    # Listener summaries as proper Pydantic models (returned by TelemetryQueryService).
    telemetry_listeners_my_app = [
        ListenerSummary(
            listener_id=1,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            app_key="my_app",
            instance_index=0,
            debounce=0.5,
            throttle=None,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='light.kitchen')",
            human_description=None,
            source_location="my_app.py:15",
            registration_source="on_initialize",
            total_invocations=10,
            successful=9,
            failed=1,
            di_failures=0,
            cancelled=0,
            total_duration_ms=20.0,
            avg_duration_ms=2.0,
            min_duration_ms=1.0,
            max_duration_ms=5.0,
            last_invoked_at=1704067200.0,
            last_error_type="ValueError",
            last_error_message="Bad state value",
        ),
        ListenerSummary(
            listener_id=2,
            handler_method="on_temp_update",
            topic="state_changed.sensor.temperature",
            app_key="my_app",
            instance_index=0,
            debounce=None,
            throttle=1.0,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='sensor.temperature')",
            human_description="React to temperature sensor changes above threshold",
            source_location="my_app.py:22",
            registration_source="on_initialize",
            total_invocations=20,
            successful=20,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=40.0,
            avg_duration_ms=2.0,
            min_duration_ms=1.0,
            max_duration_ms=5.0,
            last_invoked_at=1704067100.0,
            last_error_type=None,
            last_error_message=None,
        ),
    ]

    # broken_app listeners — registered before the app failed during init.
    telemetry_listeners_broken_app = [
        ListenerSummary(
            listener_id=3,
            handler_method="on_door_open",
            topic="state_changed.binary_sensor.door",
            app_key="broken_app",
            instance_index=0,
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description="EntityMatches(entity_id='binary_sensor.door')",
            human_description="Lock door after 5 minutes of being open",
            source_location="broken_app.py:8",
            registration_source="on_initialize",
            total_invocations=3,
            successful=1,
            failed=2,
            di_failures=0,
            cancelled=0,
            total_duration_ms=15.0,
            avg_duration_ms=5.0,
            min_duration_ms=2.0,
            max_duration_ms=10.0,
            last_invoked_at=1704067050.0,
            last_error_type="RuntimeError",
            last_error_message="Lock service timed out",
        ),
    ]

    # nosource_app listeners — empty source fields for testing hidden source display.
    telemetry_listeners_nosource_app = [
        ListenerSummary(
            listener_id=100,
            handler_method="on_event",
            topic="state_changed.switch.fan",
            app_key="nosource_app",
            instance_index=0,
            debounce=None,
            throttle=None,
            once=0,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="",
            registration_source=None,
            total_invocations=1,
            successful=1,
            failed=0,
            di_failures=0,
            cancelled=0,
            total_duration_ms=1.0,
            avg_duration_ms=1.0,
            min_duration_ms=1.0,
            max_duration_ms=1.0,
            last_invoked_at=1704067000.0,
            last_error_type=None,
            last_error_message=None,
        ),
    ]

    telemetry_listeners_by_app = {
        "my_app": telemetry_listeners_my_app,
        "broken_app": telemetry_listeners_broken_app,
        "nosource_app": telemetry_listeners_nosource_app,
    }

    # Job summaries as proper Pydantic models.
    telemetry_jobs_my_app = [
        JobSummary(
            job_id=1,
            app_key="my_app",
            instance_index=0,
            job_name="check_lights",
            handler_method="check_lights",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="my_app.py:30",
            registration_source="on_initialize",
            total_executions=15,
            successful=14,
            failed=1,
            last_executed_at=1704067200.0,
            total_duration_ms=52.5,
            avg_duration_ms=3.5,
        ),
        JobSummary(
            job_id=2,
            app_key="my_app",
            instance_index=0,
            job_name="morning_routine",
            handler_method="morning_routine",
            trigger_type="cron",
            args_json="[]",
            kwargs_json="{}",
            source_location="my_app.py:45",
            registration_source="on_initialize",
            total_executions=5,
            successful=5,
            failed=0,
            last_executed_at=1704067100.0,
            total_duration_ms=60.0,
            avg_duration_ms=12.0,
        ),
    ]

    telemetry_jobs_broken_app = [
        JobSummary(
            job_id=3,
            app_key="broken_app",
            instance_index=0,
            job_name="retry_connection",
            handler_method="retry_connection",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="broken_app.py:20",
            registration_source="on_initialize",
            total_executions=8,
            successful=3,
            failed=5,
            last_executed_at=1704067050.0,
            total_duration_ms=64.0,
            avg_duration_ms=8.0,
        ),
    ]

    # nosource_app jobs — empty source fields for testing hidden source display.
    telemetry_jobs_nosource_app = [
        JobSummary(
            job_id=100,
            app_key="nosource_app",
            instance_index=0,
            job_name="poll_sensor",
            handler_method="poll_sensor",
            trigger_type="interval",
            args_json="[]",
            kwargs_json="{}",
            source_location="",
            registration_source=None,
            total_executions=2,
            successful=2,
            failed=0,
            last_executed_at=1704067000.0,
            total_duration_ms=2.0,
            avg_duration_ms=1.0,
        ),
    ]

    telemetry_jobs_by_app = {
        "my_app": telemetry_jobs_my_app,
        "broken_app": telemetry_jobs_broken_app,
        "nosource_app": telemetry_jobs_nosource_app,
    }

    # Handler invocation records (for drill-down).
    handler_invocations = [
        HandlerInvocation(
            execution_start_ts=1704067200.0,
            duration_ms=2.5,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
        ),
        HandlerInvocation(
            execution_start_ts=1704067100.0,
            duration_ms=3.1,
            status="error",
            error_type="ValueError",
            error_message="Bad state value",
            error_traceback=(
                'Traceback (most recent call last):\n  File "my_app.py", line 18, in '
                'on_light_change\n    raise ValueError("Bad state value")\nValueError: Bad state value\n'
            ),
        ),
    ]

    # Job execution records (for drill-down).
    job_executions = [
        JobExecution(
            execution_start_ts=1704067200.0,
            duration_ms=3.0,
            status="success",
            error_type=None,
            error_message=None,
        ),
        JobExecution(
            execution_start_ts=1704067100.0,
            duration_ms=4.2,
            status="error",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
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
        old_snapshot=AppStatusSnapshot(
            running=[
                AppInstanceInfo(
                    app_key="my_app",
                    index=0,
                    instance_name="MyApp[0]",
                    class_name="MyApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="MyApp.MyApp[0]",
                ),
                AppInstanceInfo(
                    app_key="nosource_app",
                    index=0,
                    instance_name="NoSourceApp[0]",
                    class_name="NoSourceApp",
                    status=ResourceStatus.RUNNING,
                    owner_id="NoSourceApp.NoSourceApp[0]",
                ),
            ],
            failed=[
                AppInstanceInfo(
                    app_key="broken_app",
                    index=0,
                    instance_name="BrokenApp[0]",
                    class_name="BrokenApp",
                    status=ResourceStatus.FAILED,
                    error_message="Init error: bad config",
                ),
            ],
        ),
        scheduler_jobs=[
            make_job(trigger_detail="PT30S", app_key="my_app", instance_index=0),
            make_job(
                job_id="job-2",
                name="morning_routine",
                next_run="2024-01-01T07:00:00",
                trigger_type="cron",
                trigger_detail="0 7 * * * 0",
                app_key="my_app",
                instance_index=0,
            ),
        ],
    )

    hassette._telemetry_query_service.get_listener_summary = AsyncMock(
        side_effect=lambda app_key, **_: telemetry_listeners_by_app.get(app_key, [])
    )
    hassette._telemetry_query_service.get_job_summary = AsyncMock(
        side_effect=lambda app_key, **_: telemetry_jobs_by_app.get(app_key, [])
    )
    hassette._telemetry_query_service.get_handler_invocations = AsyncMock(
        return_value=handler_invocations,
    )
    hassette._telemetry_query_service.get_job_executions = AsyncMock(
        return_value=job_executions,
    )

    # Per-app health summaries for the dashboard app grid.
    hassette._telemetry_query_service.get_all_app_summaries = AsyncMock(
        return_value={
            "my_app": AppHealthSummary(
                handler_count=2,
                job_count=2,
                total_invocations=30,
                total_errors=1,
                total_executions=20,
                total_job_errors=1,
                avg_duration_ms=2.0,
                last_activity_ts=1704067200.0,
            ),
            "broken_app": AppHealthSummary(
                handler_count=1,
                job_count=1,
                total_invocations=3,
                total_errors=2,
                total_executions=8,
                total_job_errors=5,
                avg_duration_ms=5.0,
                last_activity_ts=1704067050.0,
            ),
        },
    )

    # Global summary for KPI strip — typed model. The actual mock is set up
    # further below after side-effect functions are defined.

    # Session list for the sessions page.
    hassette._telemetry_query_service.get_session_list = AsyncMock(
        return_value=[
            SessionRecord(
                id=1,
                started_at=1704067200.0,
                stopped_at=None,
                status="running",
                error_type=None,
                error_message=None,
                duration_seconds=3600.0,
            ),
            SessionRecord(
                id=2,
                started_at=1704060000.0,
                stopped_at=1704063600.0,
                status="success",
                error_type=None,
                error_message=None,
                duration_seconds=3600.0,
            ),
            SessionRecord(
                id=3,
                started_at=1704050000.0,
                stopped_at=1704053600.0,
                status="failure",
                error_type="RuntimeError",
                error_message="WebSocket connection lost",
                duration_seconds=3600.0,
            ),
        ]
    )

    # App-tier errors — shown in the default error feed.
    app_tier_errors = [
        HandlerErrorRecord(
            app_key="my_app",
            listener_id=42,
            handler_method="on_light_change",
            topic="state_changed.light.kitchen",
            execution_start_ts=1704067100.0,
            duration_ms=3.1,
            source_tier="app",
            error_type="ValueError",
            error_message="Bad state value",
        ),
        JobErrorRecord(
            app_key="my_app",
            job_id=7,
            handler_method="check_lights",
            job_name="check_lights",
            execution_start_ts=1704067000.0,
            duration_ms=4.2,
            source_tier="app",
            error_type="TimeoutError",
            error_message="Light service unavailable",
        ),
        HandlerErrorRecord(
            app_key="broken_app",
            listener_id=43,
            handler_method="on_door_open",
            topic="state_changed.binary_sensor.door",
            execution_start_ts=1704067050.0,
            duration_ms=10.0,
            source_tier="app",
            error_type="RuntimeError",
            error_message="Lock service timed out",
        ),
        # Orphan error — listener_id is None (handler was deleted)
        HandlerErrorRecord(
            app_key=None,
            listener_id=None,
            handler_method=None,
            topic=None,
            execution_start_ts=1704067000.5,
            duration_ms=1.0,
            source_tier="app",
            error_type="RuntimeError",
            error_message="Orphan error from deleted listener",
        ),
    ]

    # Framework-tier errors — shown in the unified error feed with a "Framework" badge.
    framework_tier_errors = [
        HandlerErrorRecord(
            app_key="__hassette__.service_watcher",
            listener_id=999,
            handler_method="on_state_change_dispatch",
            topic="state_changed",
            execution_start_ts=1704067200.0,
            duration_ms=1.5,
            source_tier="framework",
            error_type="DispatchError",
            error_message="Framework dispatch failed",
        ),
    ]

    def _make_errors_side_effect(source_tier: str = "all", **_kwargs):
        if source_tier == "framework":
            return framework_tier_errors
        if source_tier == "app":
            return app_tier_errors
        # "all" (default) — return both app and framework errors
        return app_tier_errors + framework_tier_errors

    hassette._telemetry_query_service.get_recent_errors = AsyncMock(
        side_effect=lambda **kwargs: _make_errors_side_effect(**kwargs)
    )

    # Framework-tier global summary for the System Health KPIs.
    framework_global_summary = GlobalSummary(
        listeners=ListenerGlobalStats(
            total_listeners=2,
            invoked_listeners=1,
            total_invocations=5,
            total_errors=1,
            total_di_failures=0,
            avg_duration_ms=1.5,
        ),
        jobs=JobGlobalStats(
            total_jobs=1,
            executed_jobs=1,
            total_executions=3,
            total_errors=0,
        ),
    )

    default_global_summary = GlobalSummary(
        listeners=ListenerGlobalStats(
            total_listeners=3,
            invoked_listeners=3,
            total_invocations=33,
            total_errors=3,
            total_di_failures=0,
            avg_duration_ms=2.5,
        ),
        jobs=JobGlobalStats(
            total_jobs=3,
            executed_jobs=3,
            total_executions=28,
            total_errors=6,
        ),
    )

    def _make_summary_side_effect(source_tier: str = "app", **_kwargs):
        if source_tier == "framework":
            return framework_global_summary
        return default_global_summary

    hassette._telemetry_query_service.get_global_summary = AsyncMock(
        side_effect=lambda **kwargs: _make_summary_side_effect(**kwargs)
    )

    def _make_error_counts_side_effect(source_tier: str = "app", **_kwargs) -> tuple[int, int]:
        if source_tier == "framework":
            return (1, 0)
        return (3, 6)

    hassette._telemetry_query_service.get_error_counts = AsyncMock(
        side_effect=lambda **kwargs: _make_error_counts_side_effect(**kwargs)
    )

    hassette.telemetry_query_service = hassette._telemetry_query_service

    # --- Session ID for error feed session scoping ---
    hassette.session_id = 1

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
