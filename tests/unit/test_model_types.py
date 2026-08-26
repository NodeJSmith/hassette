"""Unit tests confirming Pydantic rejects out-of-range values for constrained types.

Every field with an enumerated value set uses a constrained type that rejects
values outside that set at validation time.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from hassette.schemas.execution_models import ActivityFeedEntry, Execution
from hassette.schemas.log_models import LogRecord
from hassette.types.enums import ManifestStatus, ResourceStatus
from hassette.types.types import ExecutionStatus
from hassette.web.models import (
    AppHealthResponse,
    AppInstanceResponse,
    AppManifestResponse,
    DashboardAppGridEntry,
    ExecutionCompletedData,
    ListenerWithSummary,
    LogEntryResponse,
    ServiceInfoResponse,
    SystemStatusResponse,
)

STANDARD_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Every builder below sets *only* the model's required fields and passes overrides straight
# through, so a test can both feed an out-of-range value to the constrained type and read an
# untouched optional field's default. The shared src/hassette/test_utils/web_*_helpers.py
# factories fill optional fields with realistic values, which would mask exactly those defaults.


def _build(model: Any, defaults: dict[str, Any], overrides: dict[str, Any]) -> Any:
    """Instantiate `model` from `defaults`, with `overrides` replacing any of them."""
    return model(**(defaults | overrides))


def minimal_execution(**overrides: Any) -> Execution:
    """Execution with only its required fields set."""
    return _build(
        Execution,
        {
            "kind": "handler",
            "execution_start_ts": 1.0,
            "duration_ms": 10.0,
            "status": "success",
            "error_type": None,
            "error_message": None,
        },
        overrides,
    )


def minimal_manifest_response(**overrides: Any) -> AppManifestResponse:
    """AppManifestResponse with only its required fields set."""
    return _build(
        AppManifestResponse,
        {
            "app_key": "my_app",
            "class_name": "MyApp",
            "display_name": "My App",
            "filename": "my_app.py",
            "enabled": True,
            "auto_loaded": False,
            "status": "stopped",
        },
        overrides,
    )


def minimal_grid_entry(**overrides: Any) -> DashboardAppGridEntry:
    """DashboardAppGridEntry with only its required fields set."""
    return _build(
        DashboardAppGridEntry,
        {
            "app_key": "my_app",
            "status": "running",
            "display_name": "My App",
            "handler_count": 0,
            "job_count": 0,
            "total_invocations": 0,
            "total_errors": 0,
            "total_executions": 0,
            "total_job_errors": 0,
            "avg_duration_ms": 0.0,
            "last_activity_ts": None,
            "health_status": "excellent",
            "error_rate": 0.0,
            "error_rate_class": "good",
        },
        overrides,
    )


def minimal_instance_response(**overrides: Any) -> AppInstanceResponse:
    """AppInstanceResponse with only its required fields set."""
    return _build(
        AppInstanceResponse,
        {
            "app_key": "my_app",
            "index": 0,
            "instance_name": "MyApp[0]",
            "class_name": "MyApp",
            "status": ResourceStatus.RUNNING,
        },
        overrides,
    )


def minimal_health_response(**overrides: Any) -> AppHealthResponse:
    """AppHealthResponse with only its required fields set."""
    return _build(
        AppHealthResponse,
        {
            "error_rate": 0.0,
            "error_rate_class": "good",
            "handler_avg_duration": 0.0,
            "job_avg_duration": 0.0,
            "last_activity_ts": None,
            "health_status": "excellent",
        },
        overrides,
    )


def minimal_listener_with_summary(**overrides: Any) -> ListenerWithSummary:
    """ListenerWithSummary with only its required fields set."""
    return _build(
        ListenerWithSummary,
        {
            "listener_id": 1,
            "app_key": "my_app",
            "topic": "state_changed.light.kitchen",
            "handler_method": "on_light",
            "total_invocations": 0,
            "successful": 0,
            "failed": 0,
            "di_failures": 0,
            "cancelled": 0,
        },
        overrides,
    )


def minimal_log_record(**overrides: Any) -> LogRecord:
    """LogRecord with only its required fields set."""
    return _build(
        LogRecord,
        {"id": 1, "seq": 1, "timestamp": 1.0, "level": "INFO", "logger_name": "test", "message": "test"},
        overrides,
    )


def minimal_log_entry_response(**overrides: Any) -> LogEntryResponse:
    """LogEntryResponse with only its required fields set."""
    return _build(
        LogEntryResponse,
        {
            "seq": 1,
            "timestamp": 1.0,
            "level": "INFO",
            "logger_name": "test",
            "func_name": "fn",
            "lineno": 1,
            "message": "test",
        },
        overrides,
    )


def minimal_execution_completed_data(**overrides: Any) -> ExecutionCompletedData:
    """ExecutionCompletedData with only its required fields set."""
    return _build(
        ExecutionCompletedData,
        {"kind": "handler", "app_key": "my_app", "instance_index": 0, "status": "success", "duration_ms": 10.0},
        overrides,
    )


def minimal_system_status(**overrides: Any) -> SystemStatusResponse:
    """SystemStatusResponse with only its required fields set."""
    return _build(
        SystemStatusResponse,
        {
            "status": "ok",
            "websocket_connected": True,
            "bootstrap_released": True,
            "uptime_seconds": 0.0,
            "entity_count": 0,
            "app_count": 0,
        },
        overrides,
    )


class TestExecutionStatus:
    def test_rejects_bogus_status(self) -> None:
        with pytest.raises(ValidationError):
            minimal_execution(status="bogus")

    def test_accepts_all_valid_values(self) -> None:
        for value in ("success", "error", "cancelled", "timed_out", "skipped"):
            assert minimal_execution(status=value).status == ExecutionStatus(value)

    def test_rejects_bogus_on_job_execution(self) -> None:
        with pytest.raises(ValidationError):
            minimal_execution(kind="job", status="pending")

    def test_rejects_bogus_on_activity_feed_entry(self) -> None:
        with pytest.raises(ValidationError):
            ActivityFeedEntry(
                row_id="h-1",
                status="bogus",
                timestamp=1.0,
                app_key="my_app",
                handler_id=1,
                handler_name="on_event",
                kind="handler",
            )

    def test_serialises_to_plain_string(self) -> None:
        data = minimal_execution().model_dump()
        assert data["status"] == "success"
        assert isinstance(data["status"], str)


class TestManifestStatus:
    def test_rejects_value_outside_six_value_set(self) -> None:
        with pytest.raises(ValidationError):
            minimal_manifest_response(status="unknown")

    def test_accepts_all_six_values(self) -> None:
        for value in ManifestStatus:
            assert minimal_manifest_response(status=value).status == value

    def test_is_str_enum_with_expected_members(self) -> None:
        assert set(ManifestStatus) == {
            ManifestStatus.DISABLED,
            ManifestStatus.BLOCKED,
            ManifestStatus.DEGRADED,
            ManifestStatus.RUNNING,
            ManifestStatus.FAILED,
            ManifestStatus.STOPPED,
        }
        assert ManifestStatus.RUNNING == "running"
        assert isinstance(ManifestStatus.RUNNING, str)

    def test_rejects_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            minimal_grid_entry(status="active")  # not a valid ManifestStatus

    def test_autostart_defaults_to_true_when_omitted(self) -> None:
        assert minimal_manifest_response().autostart is True

    def test_autostart_round_trips_false(self) -> None:
        assert minimal_manifest_response(autostart=False).autostart is False


class TestInCurrentConfig:
    def test_app_manifest_response_defaults_to_true(self) -> None:
        assert minimal_manifest_response().in_current_config is True

    def test_app_manifest_response_round_trips_false(self) -> None:
        assert minimal_manifest_response(in_current_config=False).in_current_config is False

    def test_dashboard_app_grid_entry_defaults_to_true(self) -> None:
        assert minimal_grid_entry().in_current_config is True

    def test_dashboard_app_grid_entry_round_trips_false(self) -> None:
        assert minimal_grid_entry(in_current_config=False).in_current_config is False


class TestDashboardAppGridEntryManifestFields:
    def test_manifest_metadata_fields_have_defaults(self) -> None:
        """DashboardAppGridEntry must be constructible without any manifest metadata fields."""
        obj = minimal_grid_entry()
        assert obj.class_name == ""
        assert obj.filename == ""
        assert obj.enabled is True
        assert obj.auto_loaded is False
        assert obj.autostart is True
        assert obj.block_reason is None
        assert obj.instances == []
        assert obj.error_message is None
        assert obj.error_traceback is None

    def test_manifest_metadata_fields_round_trip(self) -> None:
        instance = minimal_instance_response()
        obj = minimal_grid_entry(
            class_name="MyApp",
            filename="my_app.py",
            enabled=False,
            auto_loaded=True,
            autostart=False,
            block_reason="disabled by config",
            instances=[instance],
            error_message="boom",
            error_traceback="Traceback...",
        )
        assert obj.class_name == "MyApp"
        assert obj.filename == "my_app.py"
        assert obj.enabled is False
        assert obj.auto_loaded is True
        assert obj.autostart is False
        assert obj.block_reason == "disabled by config"
        assert obj.instances == [instance]
        assert obj.error_message == "boom"
        assert obj.error_traceback == "Traceback..."


class TestResourceStatus:
    def test_accepts_all_nine_resource_status_values(self) -> None:
        for value in ResourceStatus:
            assert minimal_instance_response(status=value).status == value

    def test_rejects_value_not_in_resource_status(self) -> None:
        with pytest.raises(ValidationError):
            minimal_instance_response(status="active")

    def test_rejects_value_not_in_resource_status_on_service_info(self) -> None:
        with pytest.raises(ValidationError):
            ServiceInfoResponse(name="bus", status="active")

    def test_accepts_running_on_service_info(self) -> None:
        obj = ServiceInfoResponse(name="bus", status=ResourceStatus.RUNNING)
        assert obj.status == ResourceStatus.RUNNING

    def test_accepts_transient_states(self) -> None:
        for value in (
            ResourceStatus.NOT_STARTED,
            ResourceStatus.STARTING,
            ResourceStatus.STOPPING,
            ResourceStatus.EXHAUSTED_COOLING,
        ):
            assert minimal_instance_response(status=value).status == value


class TestHealthStatus:
    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            minimal_health_response(health_status="unknown")

    def test_accepts_all_four_values(self) -> None:
        for value in ("excellent", "good", "warning", "critical"):
            assert minimal_health_response(health_status=value).health_status == value

    def test_rejects_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            minimal_grid_entry(health_status="unknown")


class TestErrorRateClass:
    def test_rejects_ok(self) -> None:
        with pytest.raises(ValidationError):
            minimal_health_response(error_rate_class="ok")  # not in the 3-value set

    def test_accepts_all_three_values(self) -> None:
        for value in ("good", "warn", "bad"):
            assert minimal_health_response(error_rate_class=value).error_rate_class == value

    def test_rejects_ok_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            minimal_grid_entry(error_rate_class="ok")


class TestListenerKind:
    def test_rejects_custom(self) -> None:
        with pytest.raises(ValidationError):
            minimal_listener_with_summary(listener_kind="custom")  # not in the 3-value set

    def test_accepts_all_three_values(self) -> None:
        for value in ("state change", "service call", "event"):
            assert minimal_listener_with_summary(listener_kind=value).listener_kind == value

    def test_default_is_event(self) -> None:
        assert minimal_listener_with_summary(topic="some.custom.topic").listener_kind == "event"


class TestLogLevelType:
    def test_rejects_warn_non_standard(self) -> None:
        # non-standard; valid Python levels use "WARNING"
        with pytest.raises(ValidationError):
            minimal_log_record(level="WARN")

    def test_accepts_all_five_standard_levels_on_log_record(self) -> None:
        for level in STANDARD_LOG_LEVELS:
            assert minimal_log_record(level=level).level == level

    def test_rejects_warn_on_log_entry_response(self) -> None:
        with pytest.raises(ValidationError):
            minimal_log_entry_response(level="WARN")

    def test_rejects_bogus_source_tier_on_log_entry_response(self) -> None:
        with pytest.raises(ValidationError):
            minimal_log_entry_response(source_tier="bogus")

    def test_accepts_valid_source_tiers_on_log_entry_response(self) -> None:
        for tier in ("app", "framework", None):
            assert minimal_log_entry_response(source_tier=tier).source_tier == tier

    def test_accepts_all_five_standard_levels_on_log_entry_response(self) -> None:
        for level in STANDARD_LOG_LEVELS:
            assert minimal_log_entry_response(level=level).level == level


class TestWebSocketPayloadStatus:
    def test_execution_completed_data_rejects_bogus_kind(self) -> None:
        """Kind must be 'handler' or 'job'."""
        with pytest.raises(ValidationError):
            minimal_execution_completed_data(kind="unknown")

    def test_execution_completed_data_handler_kind(self) -> None:
        obj = minimal_execution_completed_data(listener_id=1)
        assert obj.kind == "handler"
        assert obj.listener_id == 1
        assert obj.job_id is None

    def test_execution_completed_data_job_kind(self) -> None:
        obj = minimal_execution_completed_data(
            kind="job", job_id=7, status="error", duration_ms=99.0, error_type="TimeoutError"
        )
        assert obj.kind == "job"
        assert obj.job_id == 7
        assert obj.listener_id is None
        assert obj.error_type == "TimeoutError"


class TestSystemHealthStatus:
    def test_rejects_value_outside_three_value_set(self) -> None:
        with pytest.raises(ValidationError):
            minimal_system_status(status="healthy")  # not in ("ok", "degraded", "starting")

    def test_accepts_all_three_values(self) -> None:
        for value in ("ok", "degraded", "starting"):
            assert minimal_system_status(status=value).status == value
