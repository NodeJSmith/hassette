"""Tests for source_tier propagation through data models and related changes (WP02)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from whenever import ZonedDateTime

from hassette.app.app_config import AppConfig
from hassette.bus.invocation_record import HandlerInvocationRecord
from hassette.bus.listeners import Listener
from hassette.core.commands import ExecuteJob, InvokeHandler
from hassette.core.registration import ListenerRegistration, ScheduledJobRegistration
from hassette.core.telemetry_models import HandlerErrorRecord, JobErrorRecord
from hassette.exceptions import DependencyError, DependencyInjectionError
from hassette.scheduler.classes import JobExecutionRecord, ScheduledJob
from hassette.utils.execution import ExecutionResult, track_execution

# ---------------------------------------------------------------------------
# Listener.create() — source_tier parameter
# ---------------------------------------------------------------------------


class TestListenerCreateSourceTier:
    def test_listener_create_default_source_tier(self) -> None:
        """Listener.create() with no source_tier produces 'app'."""
        task_bucket = MagicMock()
        task_bucket.make_async_adapter = lambda _fn: AsyncMock()

        async def handler(event: object) -> None:
            pass

        listener = Listener.create(
            task_bucket=task_bucket,
            owner_id="test_owner",
            topic="test.topic",
            handler=handler,
        )

        assert listener.source_tier == "app"

    def test_listener_create_framework_source_tier(self) -> None:
        """Listener.create(source_tier='framework') stores 'framework'."""
        task_bucket = MagicMock()
        task_bucket.make_async_adapter = lambda _fn: AsyncMock()

        async def handler(event: object) -> None:
            pass

        listener = Listener.create(
            task_bucket=task_bucket,
            owner_id="framework_owner",
            topic="framework.topic",
            handler=handler,
            source_tier="framework",
        )

        assert listener.source_tier == "framework"


# ---------------------------------------------------------------------------
# InvokeHandler — source_tier field
# ---------------------------------------------------------------------------


class TestInvokeHandlerSourceTier:
    def test_invoke_handler_carries_source_tier(self) -> None:
        """InvokeHandler(source_tier='framework', ...) is accessible."""
        listener = MagicMock()
        event = MagicMock()

        cmd = InvokeHandler(
            listener=listener,
            event=event,
            topic="test.topic",
            listener_id=42,
            source_tier="framework",
        )

        assert cmd.source_tier == "framework"

    def test_invoke_handler_default_source_tier(self) -> None:
        """InvokeHandler requires source_tier — omitting it raises TypeError."""
        listener = MagicMock()
        event = MagicMock()

        with pytest.raises(TypeError):
            InvokeHandler(  # pyright: ignore[reportCallIssue]
                listener=listener,
                event=event,
                topic="test.topic",
                listener_id=42,
            )


# ---------------------------------------------------------------------------
# HandlerInvocationRecord — nullable listener_id
# ---------------------------------------------------------------------------


class TestHandlerInvocationRecordNullable:
    def test_handler_invocation_record_nullable_listener_id(self) -> None:
        """HandlerInvocationRecord(listener_id=None, ...) is valid."""
        record = HandlerInvocationRecord(
            listener_id=None,
            session_id=1,
            execution_start_ts=1234567890.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
            source_tier="framework",
        )

        assert record.listener_id is None
        assert record.source_tier == "framework"

    def test_handler_invocation_record_with_int_listener_id(self) -> None:
        """HandlerInvocationRecord still accepts int listener_id."""
        record = HandlerInvocationRecord(
            listener_id=99,
            session_id=1,
            execution_start_ts=1234567890.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            error_traceback=None,
            source_tier="app",
        )

        assert record.listener_id == 99
        assert record.source_tier == "app"


# ---------------------------------------------------------------------------
# HandlerErrorRecord — nullable fields
# ---------------------------------------------------------------------------


class TestHandlerErrorRecordNullableFields:
    def test_handler_error_record_nullable_fields(self) -> None:
        """HandlerErrorRecord(listener_id=None, app_key=None, ...) is valid."""
        record = HandlerErrorRecord(
            listener_id=None,
            app_key=None,
            handler_method=None,
            topic=None,
            execution_start_ts=1234567890.0,
            duration_ms=5.0,
            error_type="ValueError",
            error_message="something went wrong",
        )

        assert record.listener_id is None
        assert record.app_key is None
        assert record.handler_method is None
        assert record.topic is None

    def test_job_error_record_nullable_fields(self) -> None:
        """JobErrorRecord nullable fields for orphan records."""
        record = JobErrorRecord(
            job_id=None,
            app_key=None,
            job_name=None,
            handler_method=None,
            execution_start_ts=1234567890.0,
            duration_ms=5.0,
            error_type="RuntimeError",
            error_message="job failed",
        )

        assert record.job_id is None
        assert record.app_key is None
        assert record.handler_method is None


# ---------------------------------------------------------------------------
# ExecutionResult — is_di_failure flag
# ---------------------------------------------------------------------------


class TestExecutionResultIsDiFailure:
    def test_execution_result_is_di_failure_default(self) -> None:
        """ExecutionResult.is_di_failure defaults to False."""
        result = ExecutionResult()
        assert result.is_di_failure is False

    async def test_is_di_failure_set_for_dependency_error(self) -> None:
        """is_di_failure is True when a DependencyError is raised."""
        with pytest.raises(DependencyError):
            async with track_execution(known_errors=(DependencyError,)) as result:
                raise DependencyError("missing dep")

        assert result.is_di_failure is True

    async def test_is_di_failure_false_for_other_errors(self) -> None:
        """is_di_failure is False for non-DependencyError exceptions."""
        with pytest.raises(ValueError, match="other error"):
            async with track_execution() as result:
                raise ValueError("other error")

        assert result.is_di_failure is False

    async def test_is_di_failure_true_for_dependency_error_subclass(self) -> None:
        """is_di_failure is True for subclasses of DependencyError."""
        with pytest.raises(DependencyInjectionError):
            async with track_execution(known_errors=()) as result:
                raise DependencyInjectionError("bad sig")

        assert result.is_di_failure is True


# ---------------------------------------------------------------------------
# AppConfig — rejects '__hassette__' sentinel app_key
# ---------------------------------------------------------------------------


class TestAppConfigSentinelGuard:
    def test_app_config_rejects_hassette_sentinel(self) -> None:
        """AppConfig(app_key='__hassette__') raises ValueError."""
        with pytest.raises(ValueError, match="__hassette__"):
            AppConfig(app_key="__hassette__")

    def test_app_config_accepts_normal_app_key(self) -> None:
        """AppConfig(app_key='my_app') succeeds."""
        config = AppConfig(app_key="my_app")
        assert config.app_key == "my_app"

    def test_app_config_accepts_empty_app_key(self) -> None:
        """AppConfig with no explicit app_key succeeds (default is empty string)."""
        config = AppConfig()
        assert config is not None


# ---------------------------------------------------------------------------
# ScheduledJob — source_tier field
# ---------------------------------------------------------------------------


class TestScheduledJobSourceTier:
    def test_scheduled_job_has_source_tier(self) -> None:
        """ScheduledJob gains source_tier field."""

        async def job_fn() -> None:
            pass

        job = ScheduledJob(
            owner_id="test_owner",
            next_run=ZonedDateTime.now("UTC"),
            job=job_fn,
            source_tier="app",
        )

        assert job.source_tier == "app"

    def test_scheduled_job_framework_source_tier(self) -> None:
        """ScheduledJob source_tier='framework' is stored correctly."""

        async def job_fn() -> None:
            pass

        job = ScheduledJob(
            owner_id="framework_owner",
            next_run=ZonedDateTime.now("UTC"),
            job=job_fn,
            source_tier="framework",
        )

        assert job.source_tier == "framework"


# ---------------------------------------------------------------------------
# JobExecutionRecord — nullable job_id and source_tier
# ---------------------------------------------------------------------------


class TestJobExecutionRecordNullable:
    def test_job_execution_record_nullable_job_id(self) -> None:
        """JobExecutionRecord(job_id=None, ...) is valid."""
        record = JobExecutionRecord(
            job_id=None,
            session_id=1,
            execution_start_ts=1234567890.0,
            duration_ms=10.0,
            status="success",
            source_tier="framework",
        )

        assert record.job_id is None
        assert record.source_tier == "framework"

    def test_job_execution_record_with_int_job_id(self) -> None:
        """JobExecutionRecord still accepts int job_id."""
        record = JobExecutionRecord(
            job_id=77,
            session_id=1,
            execution_start_ts=1234567890.0,
            duration_ms=10.0,
            status="success",
            source_tier="app",
        )

        assert record.job_id == 77
        assert record.source_tier == "app"


# ---------------------------------------------------------------------------
# ListenerRegistration and ScheduledJobRegistration — source_tier field
# ---------------------------------------------------------------------------


class TestRegistrationSourceTier:
    def test_listener_registration_has_source_tier(self) -> None:
        """ListenerRegistration gains source_tier field."""
        reg = ListenerRegistration(
            app_key="my_app",
            instance_index=0,
            handler_method="my_app.on_event",
            topic="test.topic",
            debounce=None,
            throttle=None,
            once=False,
            priority=0,
            predicate_description=None,
            human_description=None,
            source_location="app.py:10",
            registration_source=None,
            source_tier="app",
        )

        assert reg.source_tier == "app"

    def test_scheduled_job_registration_has_source_tier(self) -> None:
        """ScheduledJobRegistration gains source_tier field."""
        reg = ScheduledJobRegistration(
            app_key="my_app",
            instance_index=0,
            job_name="my_job",
            handler_method="my_app.my_job",
            trigger_type=None,
            trigger_label="once",
            trigger_detail=None,
            args_json="[]",
            kwargs_json="{}",
            source_location="app.py:20",
            registration_source=None,
            source_tier="app",
        )

        assert reg.source_tier == "app"


# ---------------------------------------------------------------------------
# ExecuteJob — source_tier field
# ---------------------------------------------------------------------------


class TestExecuteJobSourceTier:
    def test_execute_job_has_source_tier(self) -> None:
        """ExecuteJob gains source_tier field."""
        job = MagicMock()
        callable_ = AsyncMock()

        cmd = ExecuteJob(
            job=job,
            callable=callable_,
            job_db_id=42,
            source_tier="app",
        )

        assert cmd.source_tier == "app"
