"""Tests for Pydantic telemetry models."""

from hassette.core.telemetry_models import (
    AppHealthSummary,
    GlobalSummary,
    HandlerInvocation,
    JobExecution,
    JobSummary,
    ListenerSummary,
    SessionSummary,
)


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
            "last_activity_ts": 1700000000.0,
        }
        model = AppHealthSummary.model_validate(data)
        assert model.handler_count == 3
        assert model.job_count == 2
        assert model.total_invocations == 100
        assert model.total_errors == 5
        assert model.total_executions == 50
        assert model.total_job_errors == 2
        assert model.avg_duration_ms == 12.5
        assert model.last_activity_ts == 1700000000.0

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
            "last_invoked_at": 1700000000.0,
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
            "source_location": "app.py:10",
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


class TestHandlerInvocation:
    def test_handler_invocation_from_dict(self) -> None:
        data = {
            "execution_start_ts": 1700000000.0,
            "duration_ms": 12.5,
            "status": "success",
            "error_type": None,
            "error_message": None,
            "error_traceback": None,
        }
        model = HandlerInvocation.model_validate(data)
        assert model.execution_start_ts == 1700000000.0
        assert model.duration_ms == 12.5
        assert model.status == "success"
        assert model.error_type is None


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
            "last_executed_at": 1700000000.0,
            "total_duration_ms": 75.0,
            "avg_duration_ms": 25.0,
        }
        model = JobSummary.model_validate(data)
        assert model.job_id == 5
        assert model.total_executions == 3
        assert model.total_duration_ms == 75.0


class TestJobExecution:
    def test_job_execution_from_dict(self) -> None:
        data = {
            "execution_start_ts": 1700000000.0,
            "duration_ms": 20.0,
            "status": "error",
            "error_type": "RuntimeError",
            "error_message": "something broke",
        }
        model = JobExecution.model_validate(data)
        assert model.status == "error"
        assert model.error_type == "RuntimeError"


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
            "started_at": 1700000000.0,
            "last_heartbeat_at": 1700000100.0,
            "total_invocations": 50,
            "invocation_errors": 3,
            "total_executions": 10,
            "execution_errors": 1,
        }
        model = SessionSummary.model_validate(data)
        assert model.started_at == 1700000000.0
        assert model.total_invocations == 50
