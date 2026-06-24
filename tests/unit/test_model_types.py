"""Unit tests confirming Pydantic rejects out-of-range values for constrained types.

Every field with an enumerated value set uses a constrained type that rejects
values outside that set at validation time.
"""

import pytest
from pydantic import ValidationError

from hassette.schemas.telemetry_models import ActivityFeedEntry, Execution, LogRecord
from hassette.types.enums import ResourceStatus
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

# ExecutionStatus — Execution.status


class TestExecutionStatus:
    def test_rejects_bogus_status(self) -> None:
        with pytest.raises(ValidationError):
            Execution(
                kind="handler",
                execution_start_ts=1.0,
                duration_ms=10.0,
                status="bogus",
                error_type=None,
                error_message=None,
            )

    def test_accepts_all_valid_values(self) -> None:
        for value in ("success", "error", "cancelled", "timed_out"):
            obj = Execution(
                kind="handler",
                execution_start_ts=1.0,
                duration_ms=10.0,
                status=value,
                error_type=None,
                error_message=None,
            )
            assert obj.status == ExecutionStatus(value)

    def test_rejects_bogus_on_job_execution(self) -> None:
        with pytest.raises(ValidationError):
            Execution(
                kind="job",
                execution_start_ts=1.0,
                duration_ms=10.0,
                status="pending",
                error_type=None,
                error_message=None,
            )

    def test_rejects_bogus_on_activity_feed_entry(self) -> None:
        with pytest.raises(ValidationError):
            ActivityFeedEntry(
                row_id="h-1",
                status="bogus",
                timestamp=1.0,
                app_key="my_app",
                handler_name="on_event",
                kind="handler",
            )

    def test_serialises_to_plain_string(self) -> None:
        obj = Execution(
            kind="handler",
            execution_start_ts=1.0,
            duration_ms=10.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        data = obj.model_dump()
        assert data["status"] == "success"
        assert isinstance(data["status"], str)


# ManifestStatus — AppManifestResponse.status


class TestManifestStatus:
    def test_rejects_value_outside_five_value_set(self) -> None:
        with pytest.raises(ValidationError):
            AppManifestResponse(
                app_key="my_app",
                class_name="MyApp",
                display_name="My App",
                filename="my_app.py",
                enabled=True,
                auto_loaded=False,
                status="unknown",
            )

    def test_accepts_all_five_values(self) -> None:
        for value in ("disabled", "blocked", "running", "failed", "stopped"):
            obj = AppManifestResponse(
                app_key="my_app",
                class_name="MyApp",
                display_name="My App",
                filename="my_app.py",
                enabled=True,
                auto_loaded=False,
                status=value,
            )
            assert obj.status == value

    def test_rejects_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            DashboardAppGridEntry(
                app_key="my_app",
                status="active",  # not a valid ManifestStatus
                display_name="My App",
                handler_count=0,
                job_count=0,
                total_invocations=0,
                total_errors=0,
                total_executions=0,
                total_job_errors=0,
                avg_duration_ms=0.0,
                last_activity_ts=None,
                health_status="excellent",
                error_rate=0.0,
                error_rate_class="good",
            )

    def test_autostart_defaults_to_true_when_omitted(self) -> None:
        obj = AppManifestResponse(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            enabled=True,
            auto_loaded=False,
            status="stopped",
        )
        assert obj.autostart is True

    def test_autostart_round_trips_false(self) -> None:
        obj = AppManifestResponse(
            app_key="my_app",
            class_name="MyApp",
            display_name="My App",
            filename="my_app.py",
            enabled=True,
            auto_loaded=False,
            status="stopped",
            autostart=False,
        )
        assert obj.autostart is False


# ResourceStatus — AppInstanceResponse.status


class TestResourceStatus:
    def test_accepts_all_nine_resource_status_values(self) -> None:
        for value in ResourceStatus:
            obj = AppInstanceResponse(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status=value,
            )
            assert obj.status == value

    def test_rejects_value_not_in_resource_status(self) -> None:
        with pytest.raises(ValidationError):
            AppInstanceResponse(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status="active",
            )

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
            obj = AppInstanceResponse(
                app_key="my_app",
                index=0,
                instance_name="MyApp[0]",
                class_name="MyApp",
                status=value,
            )
            assert obj.status == value


# HealthStatus — AppHealthResponse.health_status


class TestHealthStatus:
    def test_rejects_unknown(self) -> None:
        with pytest.raises(ValidationError):
            AppHealthResponse(
                error_rate=0.0,
                error_rate_class="good",
                handler_avg_duration=0.0,
                job_avg_duration=0.0,
                last_activity_ts=None,
                health_status="unknown",
            )

    def test_accepts_all_four_values(self) -> None:
        for value in ("excellent", "good", "warning", "critical"):
            obj = AppHealthResponse(
                error_rate=0.0,
                error_rate_class="good",
                handler_avg_duration=0.0,
                job_avg_duration=0.0,
                last_activity_ts=None,
                health_status=value,
            )
            assert obj.health_status == value

    def test_rejects_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            DashboardAppGridEntry(
                app_key="my_app",
                status="running",
                display_name="My App",
                handler_count=0,
                job_count=0,
                total_invocations=0,
                total_errors=0,
                total_executions=0,
                total_job_errors=0,
                avg_duration_ms=0.0,
                last_activity_ts=None,
                health_status="unknown",
                error_rate=0.0,
                error_rate_class="good",
            )


# ErrorRateClass — AppHealthResponse.error_rate_class


class TestErrorRateClass:
    def test_rejects_ok(self) -> None:
        with pytest.raises(ValidationError):
            AppHealthResponse(
                error_rate=0.0,
                error_rate_class="ok",  # not in the 3-value set
                handler_avg_duration=0.0,
                job_avg_duration=0.0,
                last_activity_ts=None,
                health_status="excellent",
            )

    def test_accepts_all_three_values(self) -> None:
        for value in ("good", "warn", "bad"):
            obj = AppHealthResponse(
                error_rate=0.0,
                error_rate_class=value,
                handler_avg_duration=0.0,
                job_avg_duration=0.0,
                last_activity_ts=None,
                health_status="excellent",
            )
            assert obj.error_rate_class == value

    def test_rejects_ok_on_dashboard_grid_entry(self) -> None:
        with pytest.raises(ValidationError):
            DashboardAppGridEntry(
                app_key="my_app",
                status="running",
                display_name="My App",
                handler_count=0,
                job_count=0,
                total_invocations=0,
                total_errors=0,
                total_executions=0,
                total_job_errors=0,
                avg_duration_ms=0.0,
                last_activity_ts=None,
                health_status="excellent",
                error_rate=0.0,
                error_rate_class="ok",
            )


# ListenerKind — ListenerWithSummary.listener_kind


class TestListenerKind:
    def test_rejects_custom(self) -> None:
        with pytest.raises(ValidationError):
            ListenerWithSummary(
                listener_id=1,
                app_key="my_app",
                topic="state_changed.light.kitchen",
                listener_kind="custom",  # not in the 3-value set
                handler_method="on_light",
                total_invocations=0,
                successful=0,
                failed=0,
                di_failures=0,
                cancelled=0,
            )

    def test_accepts_all_three_values(self) -> None:
        for value in ("state change", "service call", "event"):
            obj = ListenerWithSummary(
                listener_id=1,
                app_key="my_app",
                topic="state_changed.light.kitchen",
                listener_kind=value,
                handler_method="on_light",
                total_invocations=0,
                successful=0,
                failed=0,
                di_failures=0,
                cancelled=0,
            )
            assert obj.listener_kind == value

    def test_default_is_event(self) -> None:
        obj = ListenerWithSummary(
            listener_id=1,
            app_key="my_app",
            topic="some.custom.topic",
            handler_method="on_event",
            total_invocations=0,
            successful=0,
            failed=0,
            di_failures=0,
            cancelled=0,
        )
        assert obj.listener_kind == "event"


# LOG_LEVEL_TYPE — LogRecord.level and LogEntryResponse.level


class TestLogLevelType:
    def test_rejects_warn_non_standard(self) -> None:
        with pytest.raises(ValidationError):
            LogRecord(
                id=1,
                seq=1,
                timestamp=1.0,
                level="WARN",  # non-standard; valid Python levels use "WARNING"
                logger_name="test",
                message="test",
            )

    def test_accepts_all_five_standard_levels_on_log_record(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            obj = LogRecord(
                id=1,
                seq=1,
                timestamp=1.0,
                level=level,
                logger_name="test",
                message="test",
            )
            assert obj.level == level

    def test_rejects_warn_on_log_entry_response(self) -> None:
        with pytest.raises(ValidationError):
            LogEntryResponse(
                seq=1,
                timestamp=1.0,
                level="WARN",
                logger_name="test",
                func_name="fn",
                lineno=1,
                message="test",
            )

    def test_rejects_bogus_source_tier_on_log_entry_response(self) -> None:
        with pytest.raises(ValidationError):
            LogEntryResponse(
                seq=1,
                timestamp=1.0,
                level="INFO",
                logger_name="test",
                func_name="fn",
                lineno=1,
                message="test",
                source_tier="bogus",
            )

    def test_accepts_valid_source_tiers_on_log_entry_response(self) -> None:
        for tier in ("app", "framework", None):
            obj = LogEntryResponse(
                seq=1,
                timestamp=1.0,
                level="INFO",
                logger_name="test",
                func_name="fn",
                lineno=1,
                message="test",
                source_tier=tier,
            )
            assert obj.source_tier == tier

    def test_accepts_all_five_standard_levels_on_log_entry_response(self) -> None:
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            obj = LogEntryResponse(
                seq=1,
                timestamp=1.0,
                level=level,
                logger_name="test",
                func_name="fn",
                lineno=1,
                message="test",
            )
            assert obj.level == level


# ExecutionStatus on WebSocket payload models


class TestWebSocketPayloadStatus:
    def test_execution_completed_data_rejects_bogus_kind(self) -> None:
        """kind must be 'handler' or 'job'."""
        with pytest.raises(ValidationError):
            ExecutionCompletedData(
                kind="unknown",  # pyright: ignore[reportArgumentType]
                app_key="my_app",
                instance_index=0,
                status="success",
                duration_ms=10.0,
            )

    def test_execution_completed_data_handler_kind(self) -> None:
        obj = ExecutionCompletedData(
            kind="handler",
            listener_id=1,
            app_key="my_app",
            instance_index=0,
            status="success",
            duration_ms=10.0,
        )
        assert obj.kind == "handler"
        assert obj.listener_id == 1
        assert obj.job_id is None

    def test_execution_completed_data_job_kind(self) -> None:
        obj = ExecutionCompletedData(
            kind="job",
            job_id=7,
            app_key="my_app",
            instance_index=0,
            status="error",
            duration_ms=99.0,
            error_type="TimeoutError",
        )
        assert obj.kind == "job"
        assert obj.job_id == 7
        assert obj.listener_id is None
        assert obj.error_type == "TimeoutError"


# SystemHealthStatus — SystemStatusResponse.status


class TestSystemHealthStatus:
    def test_rejects_value_outside_three_value_set(self) -> None:
        with pytest.raises(ValidationError):
            SystemStatusResponse(
                status="healthy",  # not in ("ok", "degraded", "starting")
                websocket_connected=True,
                uptime_seconds=0.0,
                entity_count=0,
                app_count=0,
                services_running=[],
            )

    def test_accepts_all_three_values(self) -> None:
        for value in ("ok", "degraded", "starting"):
            obj = SystemStatusResponse(
                status=value,
                websocket_connected=True,
                uptime_seconds=0.0,
                entity_count=0,
                app_count=0,
                services_running=[],
            )
            assert obj.status == value
