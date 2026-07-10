"""Tests for Pydantic telemetry models."""

from hassette.schemas.telemetry_models import (
    AppHealthSummary,
    Execution,
    GlobalSummary,
    JobSummary,
    ListenerSummary,
    SessionSummary,
)
from hassette.test_utils.config import TEST_EPOCH_B, TEST_SOURCE_LOCATION
from hassette.types.enums import DEFAULT_OVERLAP_MODE


class TestAppHealthSummary:
    def test_app_health_summary_from_dict(self) -> None:
        data = {
            "handler_count": 3,
            "job_count": 2,
            "total_invocations": 100,
            "total_errors": 5,
            "total_executions": 50,
            "total_job_errors": 2,
            "avg_duration_ms": 12.5,
            "last_activity_ts": TEST_EPOCH_B,
        }
        model = AppHealthSummary.model_validate(data)
        assert model.handler_count == 3
        assert model.job_count == 2
        assert model.total_invocations == 100
        assert model.total_errors == 5
        assert model.total_executions == 50
        assert model.total_job_errors == 2
        assert model.avg_duration_ms == 12.5
        assert model.last_activity_ts == TEST_EPOCH_B

    def test_app_health_summary_nullable_last_activity(self) -> None:
        data = {
            "handler_count": 0,
            "job_count": 0,
            "total_invocations": 0,
            "total_errors": 0,
            "total_executions": 0,
            "total_job_errors": 0,
            "avg_duration_ms": 0.0,
            "last_activity_ts": None,
        }
        model = AppHealthSummary.model_validate(data)
        assert model.last_activity_ts is None
        assert model.handler_count == 0


class TestListenerSummary:
    def test_listener_summary_from_dict(self) -> None:
        data = {
            "listener_id": 1,
            "app_key": "test_app",
            "instance_index": 0,
            "handler_method": "on_event",
            "topic": "hass.event.state_changed",
            "debounce": None,
            "throttle": None,
            "once": 0,
            "priority": 0,
            "predicate_description": "EntityMatches('light.kitchen')",
            "human_description": "entity light.kitchen",
            "source_location": "app.py:42",
            "registration_source": "self.bus.on_state_change(...)",
            "total_invocations": 10,
            "successful": 8,
            "failed": 2,
            "di_failures": 0,
            "cancelled": 0,
            "total_duration_ms": 150.0,
            "avg_duration_ms": 15.0,
            "min_duration_ms": 5.0,
            "max_duration_ms": 50.0,
            "last_invoked_at": TEST_EPOCH_B,
            "last_error_type": "ValueError",
            "last_error_message": "bad value",
        }
        model = ListenerSummary.model_validate(data)
        assert model.listener_id == 1
        assert model.human_description == "entity light.kitchen"
        assert model.total_invocations == 10
        assert model.successful == 8
        assert model.last_error_type == "ValueError"

    def test_listener_summary_nullable_fields(self) -> None:
        data = {
            "listener_id": 2,
            "app_key": "test_app",
            "instance_index": 0,
            "handler_method": "on_event",
            "topic": "hass.event.state_changed",
            "debounce": None,
            "throttle": None,
            "once": 0,
            "priority": 0,
            "predicate_description": None,
            "human_description": None,
            "source_location": TEST_SOURCE_LOCATION,
            "registration_source": None,
            "total_invocations": 0,
            "successful": 0,
            "failed": 0,
            "di_failures": 0,
            "cancelled": 0,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
            "min_duration_ms": 0.0,
            "max_duration_ms": 0.0,
            "last_invoked_at": None,
            "last_error_type": None,
            "last_error_message": None,
        }
        model = ListenerSummary.model_validate(data)
        assert model.human_description is None
        assert model.last_invoked_at is None


class TestExecution:
    def test_handler_execution_from_dict(self) -> None:
        data = {
            "kind": "handler",
            "listener_id": 7,
            "execution_start_ts": TEST_EPOCH_B,
            "duration_ms": 12.5,
            "status": "success",
            "error_type": None,
            "error_message": None,
        }
        model = Execution.model_validate(data)
        assert model.kind == "handler"
        assert model.listener_id == 7
        assert model.execution_start_ts == TEST_EPOCH_B
        assert model.duration_ms == 12.5
        assert model.status == "success"
        assert model.error_type is None

    def test_job_execution_from_dict(self) -> None:
        data = {
            "kind": "job",
            "job_id": 3,
            "execution_start_ts": TEST_EPOCH_B,
            "duration_ms": 20.0,
            "status": "error",
            "error_type": "RuntimeError",
            "error_message": "something broke",
        }
        model = Execution.model_validate(data)
        assert model.kind == "job"
        assert model.job_id == 3
        assert model.status == "error"
        assert model.error_type == "RuntimeError"

    def test_optional_fields_default_to_none(self) -> None:
        model = Execution.model_validate(
            {
                "kind": "handler",
                "execution_start_ts": 1.0,
                "duration_ms": 0.0,
                "status": "success",
                "error_type": None,
                "error_message": None,
            }
        )
        assert model.listener_id is None
        assert model.job_id is None
        assert model.execution_id is None
        assert model.trigger_context_id is None

    def test_error_traceback_round_trips(self) -> None:
        model = Execution.model_validate(
            {
                "kind": "handler",
                "execution_start_ts": 1.0,
                "duration_ms": 1.0,
                "status": "error",
                "error_type": "ValueError",
                "error_message": "bad",
                "error_traceback": "Traceback (most recent call last):\n  ...",
            }
        )
        assert model.error_traceback == "Traceback (most recent call last):\n  ..."


class TestJobSummary:
    def test_job_summary_from_dict(self) -> None:
        data = {
            "job_id": 5,
            "app_key": "test_app",
            "instance_index": 0,
            "job_name": "my_job",
            "handler_method": "run_job",
            "trigger_type": "interval",
            "args_json": "[]",
            "kwargs_json": "{}",
            "source_location": "app.py:55",
            "registration_source": None,
            "total_executions": 3,
            "successful": 2,
            "failed": 1,
            "last_executed_at": TEST_EPOCH_B,
            "total_duration_ms": 75.0,
            "avg_duration_ms": 25.0,
        }
        model = JobSummary.model_validate(data)
        assert model.job_id == 5
        assert model.total_executions == 3
        assert model.total_duration_ms == 75.0

    def test_job_summary_mode_default(self) -> None:
        """Mode defaults to 'single' when not supplied."""
        data = {
            "job_id": 6,
            "app_key": "test_app",
            "instance_index": 0,
            "job_name": "my_job",
            "handler_method": "run_job",
            "trigger_type": "custom",
            "args_json": "[]",
            "kwargs_json": "{}",
            "source_location": TEST_SOURCE_LOCATION,
            "registration_source": None,
            "total_executions": 0,
            "successful": 0,
            "failed": 0,
            "last_executed_at": None,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
        }
        model = JobSummary.model_validate(data)
        assert model.mode == DEFAULT_OVERLAP_MODE
        assert model.suppressed_count == 0
        assert model.dropped_count == 0

    def test_job_summary_mode_explicit_values(self) -> None:
        """mode, suppressed_count, dropped_count round-trip correctly."""
        data = {
            "job_id": 7,
            "app_key": "test_app",
            "instance_index": 0,
            "job_name": "my_job",
            "handler_method": "run_job",
            "trigger_type": "interval",
            "args_json": "[]",
            "kwargs_json": "{}",
            "source_location": TEST_SOURCE_LOCATION,
            "registration_source": None,
            "total_executions": 10,
            "successful": 8,
            "failed": 2,
            "last_executed_at": TEST_EPOCH_B,
            "total_duration_ms": 100.0,
            "avg_duration_ms": 10.0,
            "mode": "queued",
            "suppressed_count": 3,
            "dropped_count": 1,
        }
        model = JobSummary.model_validate(data)
        assert model.mode == "queued"
        assert model.suppressed_count == 3
        assert model.dropped_count == 1

    def test_job_summary_skipped_field_present(self) -> None:
        """Skipped field surfaces predicate-skip execution counts; defaults to 0."""
        assert "skipped" in JobSummary.model_fields
        assert JobSummary.model_fields["skipped"].default == 0

    def test_job_summary_predicate_description_fields(self) -> None:
        """predicate_description and human_description round-trip correctly."""
        data = {
            "job_id": 8,
            "app_key": "test_app",
            "instance_index": 0,
            "job_name": "my_job",
            "handler_method": "run_job",
            "trigger_type": "interval",
            "args_json": "[]",
            "kwargs_json": "{}",
            "source_location": TEST_SOURCE_LOCATION,
            "registration_source": None,
            "total_executions": 0,
            "successful": 0,
            "failed": 0,
            "last_executed_at": None,
            "total_duration_ms": 0.0,
            "avg_duration_ms": 0.0,
            "predicate_description": "<function is_home at 0x...>",
            "human_description": "is_home",
        }
        model = JobSummary.model_validate(data)
        assert model.predicate_description == "<function is_home at 0x...>"
        assert model.human_description == "is_home"

    def test_job_summary_invariant_with_skipped(self) -> None:
        """Successful + failed + cancelled + timed_out + skipped == total_executions when skipped > 0."""
        data = {
            "job_id": 9,
            "app_key": "test_app",
            "instance_index": 0,
            "job_name": "my_job",
            "handler_method": "run_job",
            "trigger_type": "interval",
            "args_json": "[]",
            "kwargs_json": "{}",
            "source_location": TEST_SOURCE_LOCATION,
            "registration_source": None,
            "total_executions": 10,
            "successful": 5,
            "failed": 1,
            "cancelled": 1,
            "timed_out": 1,
            "skipped": 2,
            "last_executed_at": TEST_EPOCH_B,
            "total_duration_ms": 100.0,
            "avg_duration_ms": 20.0,
        }
        model = JobSummary.model_validate(data)
        assert model.successful + model.failed + model.cancelled + model.timed_out + model.skipped == 10
        assert model.total_executions == 10


class TestGlobalSummary:
    def test_global_summary_from_dict(self) -> None:
        data = {
            "listeners": {
                "total_listeners": 5,
                "invoked_listeners": 3,
                "total_invocations": 100,
                "total_errors": 2,
                "total_di_failures": 1,
                "avg_duration_ms": 10.0,
            },
            "jobs": {
                "total_jobs": 2,
                "executed_jobs": 1,
                "total_executions": 10,
                "total_errors": 0,
            },
        }
        model = GlobalSummary.model_validate(data)
        assert model.listeners.total_listeners == 5
        assert model.jobs.total_executions == 10


class TestSessionSummary:
    def test_session_summary_from_dict(self) -> None:
        data = {
            "started_at": TEST_EPOCH_B,
            "last_heartbeat_at": 1700000100.0,
            "total_invocations": 50,
            "invocation_errors": 3,
            "total_executions": 10,
            "execution_errors": 1,
        }
        model = SessionSummary.model_validate(data)
        assert model.started_at == TEST_EPOCH_B
        assert model.total_invocations == 50
