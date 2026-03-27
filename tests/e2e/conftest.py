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
from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerInvocation,
    JobExecution,
    JobGlobalStats,
    JobSummary,
    ListenerGlobalStats,
    ListenerSummary,
    SessionSummary,
)
from hassette.logging_ import LogCaptureHandler
from hassette.test_utils.web_helpers import (
    make_job,
    make_manifest,
    make_old_app_instance,
    make_old_snapshot,
)
from hassette.test_utils.web_mocks import create_hassette_stub, create_mock_runtime_query_service
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

    telemetry_listeners_by_app = {
        "my_app": telemetry_listeners_my_app,
        "broken_app": telemetry_listeners_broken_app,
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
            trigger_value="PT30S",
            repeat=1,
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
            trigger_value="0 7 * * * 0",
            repeat=1,
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
            trigger_value="PT60S",
            repeat=1,
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

    telemetry_jobs_by_app = {
        "my_app": telemetry_jobs_my_app,
        "broken_app": telemetry_jobs_broken_app,
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

    # Wire telemetry mock to return typed models per app_key.
    from unittest.mock import AsyncMock

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

    # Global summary for KPI strip — typed model.
    hassette._telemetry_query_service.get_global_summary = AsyncMock(
        return_value=GlobalSummary(
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
    )

    # Current session summary for the session bar — typed model.
    hassette._telemetry_query_service.get_current_session_summary = AsyncMock(
        return_value=SessionSummary(
            started_at=1704067200.0,
            last_heartbeat_at=1704070800.0,
            total_invocations=33,
            invocation_errors=3,
            total_executions=28,
            execution_errors=6,
        )
    )

    # Recent errors for the error feed — includes errors from multiple apps.
    hassette._telemetry_query_service.get_recent_errors = AsyncMock(
        return_value=[
            {
                "app_key": "my_app",
                "listener_id": 42,
                "handler_method": "on_light_change",
                "topic": "state_changed.light.kitchen",
                "execution_start_ts": 1704067100.0,
                "duration_ms": 3.1,
                "error_type": "ValueError",
                "error_message": "Bad state value",
                "kind": "handler",
            },
            {
                "app_key": "my_app",
                "job_id": 7,
                "handler_method": "check_lights",
                "job_name": "check_lights",
                "execution_start_ts": 1704067000.0,
                "duration_ms": 4.2,
                "error_type": "TimeoutError",
                "error_message": "Light service unavailable",
                "kind": "job",
            },
            {
                "app_key": "broken_app",
                "listener_id": 43,
                "handler_method": "on_door_open",
                "topic": "state_changed.binary_sensor.door",
                "execution_start_ts": 1704067050.0,
                "duration_ms": 10.0,
                "error_type": "RuntimeError",
                "error_message": "Lock service timed out",
                "kind": "handler",
            },
        ]
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
def _fastapi_app(mock_hassette, runtime_query_service, _log_handler):  # noqa: ARG001
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
