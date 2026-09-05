"""Builds unified ExecutionRecord instances from execution results and commands."""

from hassette.commands import ExecuteJob, InvokeHandler
from hassette.core.execution_record import SYNTHETIC_ORIGIN, ExecutionRecord
from hassette.utils.execution import ExecutionResult


def build_execution_record(
    cmd: InvokeHandler | ExecuteJob,
    result: ExecutionResult,
    execution_start_ts: float,
    execution_id: str,
    *,
    session_id: int | None,
) -> ExecutionRecord:
    """Build a unified ExecutionRecord from the execution result and command.

    session_id is set to None if the session hasn't been created yet (pre-Phase 1).
    The actual session_id is injected at drain time in persist_batch.

    Args:
        cmd: The originating command.
        result: The execution result with timing and error info.
        execution_start_ts: Unix timestamp when execution began.
        execution_id: UUIDv7 string for this execution instance.
        session_id: The current session ID, or None if not yet created.
    """
    # `result.status` is only `None` before `track_execution()` (or the CANCELLED default
    # `_execute()` seeds before entering it) assigns a real value — every caller of
    # `build_execution_record()` does so after that assignment has happened. This is a runtime
    # contract violation, not a type-exhaustiveness guard — a direct call with an unpopulated
    # result is a real gap in the invariant, not an impossible-in-principle branch. Raise
    # explicitly rather than silently coalescing to a fallback status, so it surfaces
    # immediately instead of miscategorizing an execution's outcome.
    if result.status is None:
        raise RuntimeError("ExecutionResult.status must be populated before building a record")

    match cmd:
        case InvokeHandler():
            return ExecutionRecord(
                kind="handler",
                listener_id=cmd.listener_id,
                job_id=None,
                session_id=session_id,
                execution_start_ts=execution_start_ts,
                duration_ms=result.duration_ms,
                status=result.status,
                app_key=cmd.listener.identity.app_key,
                instance_index=cmd.listener.identity.instance_index,
                source_tier=cmd.source_tier,
                is_di_failure=result.is_di_failure,
                thread_leaked=result.thread_leaked,
                error_type=result.error_type,
                error_message=result.error_message,
                error_traceback=result.error_traceback,
                execution_id=execution_id,
                trigger_context_id=None if cmd.is_synthetic else cmd.event.payload.event_id,
                trigger_origin=SYNTHETIC_ORIGIN if cmd.is_synthetic else cmd.event.payload.origin,
            )
        case ExecuteJob():
            return ExecutionRecord(
                kind="job",
                listener_id=None,
                job_id=cmd.job_db_id,
                session_id=session_id,
                execution_start_ts=execution_start_ts,
                duration_ms=result.duration_ms,
                status=result.status,
                app_key=cmd.job.app_key,
                instance_index=cmd.job.instance_index,
                source_tier=cmd.source_tier,
                is_di_failure=result.is_di_failure,
                thread_leaked=result.thread_leaked,
                error_type=result.error_type,
                error_message=result.error_message,
                error_traceback=result.error_traceback,
                execution_id=execution_id,
                trigger_mode=cmd.trigger_mode,
            )
