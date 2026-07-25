"""Reusable factory functions for telemetry test data (executions, listeners, logs)."""

from typing import Literal

from hassette.schemas.execution_models import ActivityFeedEntry, Execution
from hassette.test_utils.config import DEFAULT_TEST_APP_KEY, TEST_EPOCH_B
from hassette.types.types import ExecutionStatus
from hassette.web.models import ListenerWithSummary, LogEntryResponse, LogsByExecutionResponse

SYNTHETIC_TIMESTAMP = TEST_EPOCH_B


def make_activity_feed_entry(
    row_id: str = "h-1",
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    timestamp: float = SYNTHETIC_TIMESTAMP,
    app_key: str = DEFAULT_TEST_APP_KEY,
    handler_id: int = 1,
    handler_name: str = "on_state_change",
    duration_ms: float | None = 12.5,
    error_type: str | None = None,
    kind: str = "handler",
) -> ActivityFeedEntry:
    """Build an ActivityFeedEntry with sensible defaults."""
    return ActivityFeedEntry(
        row_id=row_id,
        status=status,
        timestamp=timestamp,
        app_key=app_key,
        handler_id=handler_id,
        handler_name=handler_name,
        duration_ms=duration_ms,
        error_type=error_type,
        kind=kind,  # pyright: ignore[reportArgumentType]
    )


def make_listener_with_summary(
    listener_id: int = 1,
    app_key: str = DEFAULT_TEST_APP_KEY,
    instance_index: int = 0,
    topic: str = "light.kitchen",
    listener_kind: str = "state change",
    handler_method: str = "on_light_change",
    total_invocations: int = 10,
    successful: int = 9,
    failed: int = 1,
    avg_duration_ms: float = 25.0,
    last_invoked_at: float | None = SYNTHETIC_TIMESTAMP,
    last_error_type: str | None = None,
    last_error_message: str | None = None,
    entity_id: str | None = None,
) -> ListenerWithSummary:
    """Build a ListenerWithSummary with sensible defaults."""
    return ListenerWithSummary(
        listener_id=listener_id,
        app_key=app_key,
        instance_index=instance_index,
        topic=topic,
        listener_kind=listener_kind,  # pyright: ignore[reportArgumentType]
        handler_method=handler_method,
        total_invocations=total_invocations,
        successful=successful,
        failed=failed,
        di_failures=0,
        cancelled=0,
        avg_duration_ms=avg_duration_ms,
        last_invoked_at=last_invoked_at,
        last_error_type=last_error_type,
        last_error_message=last_error_message,
        entity_id=entity_id,
    )


def make_execution(
    kind: Literal["handler", "job"] = "handler",
    execution_start_ts: float = SYNTHETIC_TIMESTAMP,
    duration_ms: float = 12.5,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    error_type: str | None = None,
    error_message: str | None = None,
    execution_id: str | None = None,
    listener_id: int | None = None,
    job_id: int | None = None,
) -> Execution:
    """Build an Execution with sensible defaults."""
    return Execution(
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


def make_log_entry_response(
    seq: int = 1,
    timestamp: float = SYNTHETIC_TIMESTAMP,
    level: str = "INFO",
    logger_name: str = "hassette.app.test_app",
    func_name: str | None = "on_state_change",
    lineno: int | None = 42,
    message: str = "Handler invoked",
    exc_info: str | None = None,
    app_key: str | None = DEFAULT_TEST_APP_KEY,
    execution_id: str | None = None,
    instance_name: str | None = None,
    instance_index: int | None = 0,
    source_tier: str | None = "app",
) -> LogEntryResponse:
    """Build a LogEntryResponse with sensible defaults."""
    return LogEntryResponse(
        seq=seq,
        timestamp=timestamp,
        level=level,  # pyright: ignore[reportArgumentType]
        logger_name=logger_name,
        func_name=func_name,
        lineno=lineno,
        message=message,
        exc_info=exc_info,
        app_key=app_key,
        execution_id=execution_id,
        instance_name=instance_name,
        instance_index=instance_index,
        source_tier=source_tier,  # pyright: ignore[reportArgumentType]
    )


def make_logs_by_execution_response(
    records: list[LogEntryResponse] | None = None,
    truncated: bool = False,
    retention_expired: bool = False,
) -> LogsByExecutionResponse:
    """Build a LogsByExecutionResponse with sensible defaults."""
    if records is None:
        records = [make_log_entry_response()]
    return LogsByExecutionResponse(
        records=records,
        truncated=truncated,
        retention_expired=retention_expired,
    )
