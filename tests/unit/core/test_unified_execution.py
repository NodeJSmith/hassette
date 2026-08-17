"""Unit tests for the unified Execution model and ExecutionRecord dataclass.

Covers:
- Execution model has a kind discriminator
- kind only accepts 'handler' or 'job'
- invalid kind values are rejected by Pydantic
- new columns exist with correct defaults
"""

from typing import Literal

import pytest
from pydantic import ValidationError

from hassette.core.execution_record import ExecutionRecord
from hassette.schemas.execution_models import Execution
from hassette.test_utils.config import TEST_EPOCH_B
from hassette.test_utils.factories import make_execution_record
from hassette.test_utils.web_telemetry_helpers import make_execution
from hassette.types.types import ExecutionStatus


def build_execution(
    *,
    kind: Literal["handler", "job"] = "handler",
    execution_start_ts: float = TEST_EPOCH_B,
    duration_ms: float = 12.5,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_id: str | None = None,
    listener_id: int | None = None,
    job_id: int | None = None,
    trigger_context_id: str | None = None,
    trigger_origin: str | None = None,
    trigger_mode: str | None = None,
    retry_count: int = 0,
    attempt_number: int = 1,
    args_json: str = "[]",
    kwargs_json: str = "{}",
) -> Execution:
    """Build an Execution via the shared make_execution() factory, layering the extra
    per-execution columns (trigger metadata, retry/attempt counters, JSON payloads) that
    make_execution()'s signature doesn't expose on top via model_copy — Execution carries more
    fields than the shared web-layer factory covers.
    """
    base = make_execution(
        kind=kind,
        execution_start_ts=execution_start_ts,
        duration_ms=duration_ms,
        status=status,
        error_type=error_type,
        error_message=error_message,
        execution_id=execution_id,
        listener_id=listener_id,
        job_id=job_id,
    )
    return base.model_copy(
        update={
            "trigger_context_id": trigger_context_id,
            "trigger_origin": trigger_origin,
            "trigger_mode": trigger_mode,
            "retry_count": retry_count,
            "attempt_number": attempt_number,
            "args_json": args_json,
            "kwargs_json": kwargs_json,
        }
    )


def build_execution_minimal(*, kind: Literal["handler", "job"] = "handler") -> Execution:
    """Construct an Execution from only its required fields, leaving every new column
    (trigger_mode, retry_count, attempt_number, args_json, kwargs_json) at its real model
    default. Unlike build_execution()'s model_copy(), this doesn't overwrite those defaults,
    so it's the right constructor for tests that assert the default itself.
    """
    return Execution(
        kind=kind,
        execution_start_ts=TEST_EPOCH_B,
        duration_ms=5.0,
        status=ExecutionStatus.SUCCESS,
        error_type=None,
        error_message=None,
    )


def build_execution_record_minimal(*, kind: Literal["handler", "job"] = "handler") -> ExecutionRecord:
    """Construct an ExecutionRecord from only its required fields, leaving every new column
    at its real dataclass default — see build_execution_minimal() for why this matters.
    """
    return ExecutionRecord(
        kind=kind,
        session_id=1,
        execution_start_ts=TEST_EPOCH_B,
        duration_ms=5.0,
        status="success",
    )


class TestExecutionModelKindHandler:
    def test_kind_handler_accepted(self) -> None:
        """kind='handler' is a valid discriminator value."""
        model = build_execution()
        assert model.kind == "handler"

    def test_kind_job_accepted(self) -> None:
        """kind='job' is a valid discriminator value."""
        model = build_execution(
            kind="job",
            duration_ms=20.0,
            status=ExecutionStatus.ERROR,
            error_type="RuntimeError",
            error_message="oops",
        )
        assert model.kind == "job"

    def test_handler_only_fields_present_on_handler(self) -> None:
        """Handler-only fields can be set when kind='handler'."""
        model = build_execution(duration_ms=5.0, trigger_context_id="ctx-abc", trigger_origin="LOCAL")
        assert model.trigger_context_id == "ctx-abc"
        assert model.trigger_origin == "LOCAL"

    def test_handler_only_fields_default_none_on_job(self) -> None:
        """trigger_context_id and trigger_origin default to None when kind='job'."""
        model = build_execution(kind="job", duration_ms=8.0)
        assert model.trigger_context_id is None
        assert model.trigger_origin is None

    def test_fk_identity_fields_default_none_and_settable(self) -> None:
        """listener_id is set for handler rows, job_id for job rows; both default None."""
        handler = build_execution(listener_id=42, duration_ms=5.0)
        assert handler.listener_id == 42
        assert handler.job_id is None

        job = build_execution(kind="job", job_id=7, duration_ms=5.0)
        assert job.job_id == 7
        assert job.listener_id is None


class TestExecutionModelInvalidKind:
    def test_invalid_kind_raises_validation_error(self) -> None:
        """Kind rejects values other than 'handler' or 'job'."""
        with pytest.raises(ValidationError):
            build_execution(kind="invocation", duration_ms=5.0)  # pyright: ignore[reportArgumentType]

    def test_empty_string_kind_raises_validation_error(self) -> None:
        """Empty string is not a valid kind."""
        with pytest.raises(ValidationError):
            build_execution(kind="", duration_ms=5.0)  # pyright: ignore[reportArgumentType]

    def test_numeric_kind_raises_validation_error(self) -> None:
        """Numeric values are not valid kind values."""
        with pytest.raises(ValidationError):
            build_execution(kind=1, duration_ms=5.0)  # pyright: ignore[reportArgumentType]


class TestExecutionModelNewColumns:
    """New columns on Execution exist with correct defaults."""

    def test_trigger_mode_defaults_none(self) -> None:
        model = build_execution_minimal()
        assert model.trigger_mode is None

    def test_retry_count_defaults_zero(self) -> None:
        model = build_execution_minimal(kind="job")
        assert model.retry_count == 0

    def test_attempt_number_defaults_one(self) -> None:
        model = build_execution_minimal()
        assert model.attempt_number == 1

    def test_args_json_defaults_empty_list(self) -> None:
        model = build_execution_minimal(kind="job")
        assert model.args_json == "[]"

    def test_kwargs_json_defaults_empty_dict(self) -> None:
        model = build_execution_minimal()
        assert model.kwargs_json == "{}"

    def test_new_columns_can_be_set(self) -> None:
        """All new columns accept non-default values."""
        model = build_execution(
            kind="job",
            duration_ms=5.0,
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


class TestExecutionRecordKind:
    def test_handler_kind_construction(self) -> None:
        """ExecutionRecord accepts kind='handler'."""
        record = make_execution_record(execution_start_ts=TEST_EPOCH_B, duration_ms=10.0, listener_id=42)
        assert record.kind == "handler"
        assert record.listener_id == 42
        assert record.job_id is None

    def test_job_kind_construction(self) -> None:
        """ExecutionRecord accepts kind='job'."""
        record = make_execution_record(
            kind="job", execution_start_ts=TEST_EPOCH_B, duration_ms=10.0, listener_id=None, job_id=7
        )
        assert record.kind == "job"
        assert record.job_id == 7
        assert record.listener_id is None

    def test_handler_only_fields_default_none_for_job(self) -> None:
        """trigger_context_id and trigger_origin default None when kind='job'."""
        record = make_execution_record(
            kind="job", execution_start_ts=TEST_EPOCH_B, duration_ms=5.0, listener_id=None, job_id=3
        )
        assert record.trigger_context_id is None
        assert record.trigger_origin is None

    def test_app_key_and_instance_index_present(self) -> None:
        """app_key and instance_index fields exist on ExecutionRecord."""
        record = make_execution_record(
            execution_start_ts=TEST_EPOCH_B, duration_ms=5.0, app_key="my_app", instance_index=2
        )
        assert record.app_key == "my_app"
        assert record.instance_index == 2


class TestExecutionRecordNewColumns:
    """New columns on ExecutionRecord exist with correct defaults."""

    def test_trigger_mode_defaults_none(self) -> None:
        record = build_execution_record_minimal()
        assert record.trigger_mode is None

    def test_retry_count_defaults_zero(self) -> None:
        record = build_execution_record_minimal(kind="job")
        assert record.retry_count == 0

    def test_attempt_number_defaults_one(self) -> None:
        record = build_execution_record_minimal()
        assert record.attempt_number == 1

    def test_args_json_defaults_empty_list(self) -> None:
        record = build_execution_record_minimal(kind="job")
        assert record.args_json == "[]"

    def test_kwargs_json_defaults_empty_dict(self) -> None:
        record = build_execution_record_minimal()
        assert record.kwargs_json == "{}"

    def test_new_columns_can_be_set(self) -> None:
        record = make_execution_record(
            kind="job",
            execution_start_ts=TEST_EPOCH_B,
            duration_ms=5.0,
            status="error",
            listener_id=None,
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
        record = make_execution_record(execution_start_ts=TEST_EPOCH_B, duration_ms=5.0)
        with pytest.raises((AttributeError, TypeError)):
            record.status = "error"  # pyright: ignore[reportAttributeAccessIssue]
