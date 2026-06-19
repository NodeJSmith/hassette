"""Unit tests for the unified Execution model and ExecutionRecord dataclass (T07).

Covers:
- FR#1: Execution model has a kind discriminator
- FR#17: kind only accepts 'handler' or 'job'
- AC#11: invalid kind values are rejected by Pydantic
- AC#12: new columns exist with correct defaults
"""

import pytest
from pydantic import ValidationError

from hassette.core.execution_record import ExecutionRecord
from hassette.core.telemetry_models import Execution

# Execution model — shared/base field construction


class TestExecutionModelKindHandler:
    def test_kind_handler_accepted(self) -> None:
        """kind='handler' is a valid discriminator value."""
        model = Execution(
            kind="handler",
            execution_start_ts=1700000000.0,
            duration_ms=12.5,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.kind == "handler"

    def test_kind_job_accepted(self) -> None:
        """kind='job' is a valid discriminator value."""
        model = Execution(
            kind="job",
            execution_start_ts=1700000000.0,
            duration_ms=20.0,
            status="error",
            error_type="RuntimeError",
            error_message="oops",
        )
        assert model.kind == "job"

    def test_handler_only_fields_present_on_handler(self) -> None:
        """Handler-only fields can be set when kind='handler'."""
        model = Execution(
            kind="handler",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            trigger_context_id="ctx-abc",
            trigger_origin="LOCAL",
        )
        assert model.trigger_context_id == "ctx-abc"
        assert model.trigger_origin == "LOCAL"

    def test_handler_only_fields_default_none_on_job(self) -> None:
        """trigger_context_id and trigger_origin default to None when kind='job'."""
        model = Execution(
            kind="job",
            execution_start_ts=1700000000.0,
            duration_ms=8.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.trigger_context_id is None
        assert model.trigger_origin is None

    def test_fk_identity_fields_default_none_and_settable(self) -> None:
        """listener_id is set for handler rows, job_id for job rows; both default None."""
        handler = Execution(
            kind="handler",
            listener_id=42,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert handler.listener_id == 42
        assert handler.job_id is None

        job = Execution(
            kind="job",
            job_id=7,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert job.job_id == 7
        assert job.listener_id is None


class TestExecutionModelInvalidKind:
    def test_invalid_kind_raises_validation_error(self) -> None:
        """kind rejects values other than 'handler' or 'job' (AC#11, FR#17)."""
        with pytest.raises(ValidationError):
            Execution(
                kind="invocation",  # pyright: ignore[reportArgumentType]
                execution_start_ts=1700000000.0,
                duration_ms=5.0,
                status="success",
                error_type=None,
                error_message=None,
            )

    def test_empty_string_kind_raises_validation_error(self) -> None:
        """Empty string is not a valid kind."""
        with pytest.raises(ValidationError):
            Execution(
                kind="",  # pyright: ignore[reportArgumentType]
                execution_start_ts=1700000000.0,
                duration_ms=5.0,
                status="success",
                error_type=None,
                error_message=None,
            )

    def test_numeric_kind_raises_validation_error(self) -> None:
        """Numeric values are not valid kind values."""
        with pytest.raises(ValidationError):
            Execution(
                kind=1,  # pyright: ignore[reportArgumentType]
                execution_start_ts=1700000000.0,
                duration_ms=5.0,
                status="success",
                error_type=None,
                error_message=None,
            )


class TestExecutionModelNewColumns:
    """AC#12: new columns exist with correct defaults."""

    def test_trigger_mode_defaults_none(self) -> None:
        model = Execution(
            kind="handler",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.trigger_mode is None

    def test_retry_count_defaults_zero(self) -> None:
        model = Execution(
            kind="job",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.retry_count == 0

    def test_attempt_number_defaults_one(self) -> None:
        model = Execution(
            kind="handler",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.attempt_number == 1

    def test_args_json_defaults_empty_list(self) -> None:
        model = Execution(
            kind="job",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.args_json == "[]"

    def test_kwargs_json_defaults_empty_dict(self) -> None:
        model = Execution(
            kind="handler",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
        )
        assert model.kwargs_json == "{}"

    def test_new_columns_can_be_set(self) -> None:
        """All new columns accept non-default values."""
        model = Execution(
            kind="job",
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            error_type=None,
            error_message=None,
            trigger_mode="cron",
            retry_count=2,
            attempt_number=3,
            args_json="[1, 2]",
            kwargs_json='{"key": "value"}',
        )
        assert model.trigger_mode == "cron"
        assert model.retry_count == 2
        assert model.attempt_number == 3
        assert model.args_json == "[1, 2]"
        assert model.kwargs_json == '{"key": "value"}'


# ExecutionRecord dataclass


class TestExecutionRecordKind:
    def test_handler_kind_construction(self) -> None:
        """ExecutionRecord accepts kind='handler'."""
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=10.0,
            status="success",
            listener_id=42,
        )
        assert record.kind == "handler"
        assert record.listener_id == 42
        assert record.job_id is None

    def test_job_kind_construction(self) -> None:
        """ExecutionRecord accepts kind='job'."""
        record = ExecutionRecord(
            kind="job",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=10.0,
            status="success",
            job_id=7,
        )
        assert record.kind == "job"
        assert record.job_id == 7
        assert record.listener_id is None

    def test_handler_only_fields_default_none_for_job(self) -> None:
        """trigger_context_id and trigger_origin default None when kind='job'."""
        record = ExecutionRecord(
            kind="job",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            job_id=3,
        )
        assert record.trigger_context_id is None
        assert record.trigger_origin is None

    def test_app_key_and_instance_index_present(self) -> None:
        """app_key and instance_index fields exist (added in T06)."""
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
            listener_id=1,
            app_key="my_app",
            instance_index=2,
        )
        assert record.app_key == "my_app"
        assert record.instance_index == 2


class TestExecutionRecordNewColumns:
    """AC#12: new columns on ExecutionRecord with correct defaults."""

    def test_trigger_mode_defaults_none(self) -> None:
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        assert record.trigger_mode is None

    def test_retry_count_defaults_zero(self) -> None:
        record = ExecutionRecord(
            kind="job",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        assert record.retry_count == 0

    def test_attempt_number_defaults_one(self) -> None:
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        assert record.attempt_number == 1

    def test_args_json_defaults_empty_list(self) -> None:
        record = ExecutionRecord(
            kind="job",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        assert record.args_json == "[]"

    def test_kwargs_json_defaults_empty_dict(self) -> None:
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        assert record.kwargs_json == "{}"

    def test_new_columns_can_be_set(self) -> None:
        record = ExecutionRecord(
            kind="job",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="error",
            job_id=99,
            trigger_mode="interval",
            retry_count=1,
            attempt_number=2,
            args_json="[42]",
            kwargs_json='{"x": 1}',
        )
        assert record.trigger_mode == "interval"
        assert record.retry_count == 1
        assert record.attempt_number == 2
        assert record.args_json == "[42]"
        assert record.kwargs_json == '{"x": 1}'

    def test_execution_record_is_frozen(self) -> None:
        """ExecutionRecord is a frozen dataclass (immutability invariant)."""
        record = ExecutionRecord(
            kind="handler",
            session_id=1,
            execution_start_ts=1700000000.0,
            duration_ms=5.0,
            status="success",
        )
        with pytest.raises((AttributeError, TypeError)):
            record.status = "error"  # pyright: ignore[reportAttributeAccessIssue]
