"""Unit tests confirming Pydantic rejects out-of-range values for constrained types.

Every field with an enumerated value set uses a constrained type that rejects
values outside that set at validation time.
"""

from typing import Any

import pytest
from hassette_wire import (
    ActivityFeedEntry,
    AppActivity,
    AppActivityStats,
    AppGridResponse,
    AppHealth,
    AppInstance,
    AppStatus,
    AppSummary,
    Execution,
    ExecutionCompletedData,
    ExecutionStatus,
    LastErrorResult,
    ListenerSummary,
    LogEntry,
    ResourceRole,
    ResourceStatus,
    ServiceInfo,
    SystemStatusResponse,
)
from pydantic import ValidationError

from hassette.schemas.log_models import LogRecord
from tests.support.web_response_helpers import make_app_activity

STANDARD_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Every builder below sets *only* the model's required fields and passes overrides straight
# through, so a test can both feed an out-of-range value to the constrained type and read an
# untouched optional field's default. The shared tests/support/web_*_helpers.py
# factories fill optional fields with realistic values, which would mask exactly those defaults.


def build(model: Any, defaults: dict[str, Any], overrides: dict[str, Any]) -> Any:
    """Instantiate `model` from `defaults`, with `overrides` replacing any of them."""
    return model(**(defaults | overrides))


def minimal_execution(**overrides: Any) -> Execution:
    """Execution with only its required fields set."""
    return build(
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


def minimal_app_summary(**overrides: Any) -> AppSummary:
    """AppSummary with only its required fields set."""
    return build(
        AppSummary,
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


def minimal_app_instance(**overrides: Any) -> AppInstance:
    """AppInstance with only its required fields set."""
    return build(
        AppInstance,
        {
            "app_key": "my_app",
            "index": 0,
            "instance_name": "MyApp[0]",
            "class_name": "MyApp",
            "status": ResourceStatus.RUNNING,
        },
        overrides,
    )


def minimal_app_health(**overrides: Any) -> AppHealth:
    """AppHealth with only its required fields set."""
    return build(
        AppHealth,
        {
            "error_rate": 0.0,
            "error_rate_class": "good",
            "health_status": "excellent",
            "last_activity_ts": None,
            "handler_avg_duration_ms": None,
            "job_avg_duration_ms": None,
        },
        overrides,
    )


def minimal_listener_summary(**overrides: Any) -> ListenerSummary:
    """ListenerSummary with only its required fields set."""
    return build(
        ListenerSummary,
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
    return build(
        LogRecord,
        {"id": 1, "seq": 1, "timestamp": 1.0, "level": "INFO", "logger_name": "test", "message": "test"},
        overrides,
    )


def minimal_log_entry(**overrides: Any) -> LogEntry:
    """LogEntry with only its required fields set."""
    return build(
        LogEntry,
        {
            "id": 1,
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
    return build(
        ExecutionCompletedData,
        {"kind": "handler", "app_key": "my_app", "instance_index": 0, "status": "success", "duration_ms": 10.0},
        overrides,
    )


def minimal_system_status(**overrides: Any) -> SystemStatusResponse:
    """SystemStatusResponse with only its required fields set."""
    return build(
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


class TestAppStatus:
    def test_rejects_value_outside_app_status_set(self) -> None:
        with pytest.raises(ValidationError):
            minimal_app_summary(status="unknown")

    def test_accepts_every_app_status(self) -> None:
        for value in AppStatus:
            assert minimal_app_summary(status=value).status == value

    def test_is_str_enum_with_expected_members(self) -> None:
        assert set(AppStatus) == {
            AppStatus.DISABLED,
            AppStatus.BLOCKED,
            AppStatus.DEGRADED,
            AppStatus.RUNNING,
            AppStatus.FAILED,
            AppStatus.STOPPED,
        }
        assert AppStatus.RUNNING == "running"
        assert isinstance(AppStatus.RUNNING, str)

    def test_autostart_defaults_to_true_when_omitted(self) -> None:
        assert minimal_app_summary().autostart is True

    def test_autostart_round_trips_false(self) -> None:
        assert minimal_app_summary(autostart=False).autostart is False


class TestInCurrentConfig:
    def test_app_summary_defaults_to_true(self) -> None:
        assert minimal_app_summary().in_current_config is True

    def test_app_summary_round_trips_false(self) -> None:
        assert minimal_app_summary(in_current_config=False).in_current_config is False


class TestAppGridResponse:
    def test_since_defaults_to_all_time(self) -> None:
        assert AppGridResponse(apps=[]).since is None


class TestAppActivity:
    @pytest.mark.parametrize("part", ["stats", "activity_buckets", "last_error", "blocking_event_count"])
    def test_a_missing_part_key_fails_validation(self, part: str) -> None:
        """Every part is required-nullable: an absent key can't read as "not computed"."""
        body = {"stats": None, "activity_buckets": None, "last_error": None, "blocking_event_count": None}
        del body[part]
        with pytest.raises(ValidationError):
            AppActivity.model_validate(body)

    def test_explicit_nulls_validate(self) -> None:
        body = {"stats": None, "activity_buckets": None, "last_error": None, "blocking_event_count": None}
        assert AppActivity.model_validate(body).stats is None

    @pytest.mark.parametrize("field", ["total_timed_out", "total_job_timed_out"])
    def test_stats_timeout_counts_are_required(self, field: str) -> None:
        """A missing count fails validation instead of reading as a real zero inside a populated part."""
        body = make_app_activity().model_dump(mode="json")["stats"]
        del body[field]
        with pytest.raises(ValidationError):
            AppActivityStats.model_validate(body)

    def test_last_error_result_requires_its_error_key(self) -> None:
        """``{error: null}`` (ran, found none) must be sent explicitly, never inferred from ``{}``."""
        with pytest.raises(ValidationError):
            LastErrorResult.model_validate({})


class TestResourceStatus:
    def test_accepts_all_nine_resource_status_values(self) -> None:
        for value in ResourceStatus:
            assert minimal_app_instance(status=value).status == value

    def test_rejects_value_not_in_resource_status(self) -> None:
        with pytest.raises(ValidationError):
            minimal_app_instance(status="active")

    def test_rejects_value_not_in_resource_status_on_service_info(self) -> None:
        with pytest.raises(ValidationError):
            ServiceInfo(name="bus", status="active", role=ResourceRole.SERVICE)

    def test_accepts_running_on_service_info(self) -> None:
        obj = ServiceInfo(name="bus", status=ResourceStatus.RUNNING, role=ResourceRole.SERVICE)
        assert obj.status == ResourceStatus.RUNNING

    def test_accepts_transient_states(self) -> None:
        for value in (
            ResourceStatus.NOT_STARTED,
            ResourceStatus.STARTING,
            ResourceStatus.STOPPING,
            ResourceStatus.EXHAUSTED_COOLING,
        ):
            assert minimal_app_instance(status=value).status == value


class TestHealthStatus:
    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            minimal_app_health(health_status="unknown")

    def test_accepts_all_four_values(self) -> None:
        for value in ("excellent", "good", "warning", "critical"):
            assert minimal_app_health(health_status=value).health_status == value


class TestErrorRateClass:
    def test_rejects_ok(self) -> None:
        with pytest.raises(ValidationError):
            minimal_app_health(error_rate_class="ok")  # not in the 3-value set

    def test_accepts_all_three_values(self) -> None:
        for value in ("good", "warn", "bad"):
            assert minimal_app_health(error_rate_class=value).error_rate_class == value


class TestListenerKind:
    def test_rejects_custom(self) -> None:
        with pytest.raises(ValidationError):
            minimal_listener_summary(listener_kind="custom")  # not in the 3-value set

    def test_accepts_all_three_values(self) -> None:
        for value in ("state change", "service call", "event"):
            assert minimal_listener_summary(listener_kind=value).listener_kind == value

    def test_default_is_event(self) -> None:
        assert minimal_listener_summary(topic="some.custom.topic").listener_kind == "event"


class TestLogLevelType:
    def test_rejects_warn_non_standard(self) -> None:
        # non-standard; valid Python levels use "WARNING"
        with pytest.raises(ValidationError):
            minimal_log_record(level="WARN")

    def test_accepts_all_five_standard_levels_on_log_record(self) -> None:
        for level in STANDARD_LOG_LEVELS:
            assert minimal_log_record(level=level).level == level

    def test_rejects_warn_on_log_entry(self) -> None:
        with pytest.raises(ValidationError):
            minimal_log_entry(level="WARN")

    def test_rejects_bogus_source_tier_on_log_entry(self) -> None:
        with pytest.raises(ValidationError):
            minimal_log_entry(source_tier="bogus")

    def test_accepts_valid_source_tiers_on_log_entry(self) -> None:
        for tier in ("app", "framework", None):
            assert minimal_log_entry(source_tier=tier).source_tier == tier

    def test_accepts_all_five_standard_levels_on_log_entry(self) -> None:
        for level in STANDARD_LOG_LEVELS:
            assert minimal_log_entry(level=level).level == level


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
