"""Builds unified ExecutionRecord instances from execution results and commands."""

import json
import logging
from typing import TYPE_CHECKING, Any, TypedDict

from hassette.commands import ExecuteJob, InvokeHandler
from hassette.core.execution_record import SYNTHETIC_ORIGIN, ExecutionRecord
from hassette.events.base import HassPayload
from hassette.events.hass.hass import RawStateChangePayload
from hassette.utils.execution import ExecutionResult

if TYPE_CHECKING:
    from hassette.bus.listeners import Listener
    from hassette.events import AnyEvent
    from hassette.events.hass.raw import HassStateDict

TRIGGER_VALUE_MAX_CHARS = 255
"""Cap, in code points and counting the trailing ellipsis, on a stored old/new trigger value.

Matches Home Assistant's own 255-character state limit, so a state value is never cut; only large
attribute values are.
"""

TRUNCATION_MARK = "…"

LOGGER = logging.getLogger(__name__)

_MISSING = object()
"""Sentinel for a state or attribute key that is absent, as opposed to an explicit JSON null."""


class TriggerRecordFields(TypedDict):
    """``ExecutionRecord``'s ``trigger_*`` keyword arguments for a handler run, built by :func:`summarize_trigger`."""

    trigger_context_id: str | None
    trigger_origin: str | None
    trigger_parent_id: str | None
    trigger_topic: str | None
    trigger_entity_id: str | None
    trigger_old_value: str | None
    trigger_new_value: str | None


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
                source_tier=cmd.source_tier,
                is_di_failure=result.is_di_failure,
                thread_leaked=result.thread_leaked,
                error_type=result.error_type,
                error_message=result.error_message,
                error_traceback=result.error_traceback,
                execution_id=execution_id,
                **summarize_trigger(cmd.event, cmd.listener, is_synthetic=cmd.is_synthetic),
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
                source_tier=cmd.source_tier,
                is_di_failure=result.is_di_failure,
                thread_leaked=result.thread_leaked,
                error_type=result.error_type,
                error_message=result.error_message,
                error_traceback=result.error_traceback,
                execution_id=execution_id,
                trigger_mode=cmd.trigger_mode,
            )


def summarize_trigger(event: "AnyEvent", listener: "Listener", *, is_synthetic: bool) -> TriggerRecordFields:
    """Summarize which event, entity and value change fired ``listener``. Never raises.

    The event's id, origin, parent id and topic are read directly. The entity and old/new values
    depend on the payload's shape, so a failure there leaves only those three None and is logged,
    without the event's values, once per failed row instead of failing the run.

    A row whose event was built from the cached state (``is_synthetic``: an immediate-fire run, or a
    predicate that raised on an immediate fire or a duration fire-time recheck) keeps the event's real
    context but is labelled with ``SYNTHETIC_ORIGIN``, since Home Assistant didn't send that event.
    """
    payload = event.payload
    fields: TriggerRecordFields = {
        "trigger_context_id": payload.event_id or None,
        "trigger_origin": SYNTHETIC_ORIGIN if is_synthetic else payload.origin,
        "trigger_parent_id": payload.context.parent_id if isinstance(payload, HassPayload) else None,
        "trigger_topic": str(event.topic),
        "trigger_entity_id": None,
        "trigger_old_value": None,
        "trigger_new_value": None,
    }
    try:
        entity_id, old_value, new_value = extract_change(event, listener)
    except Exception:
        LOGGER.exception("Failed to summarize the triggering event for %s; entity and values left empty", listener)
        return fields
    return {**fields, "trigger_entity_id": entity_id, "trigger_old_value": old_value, "trigger_new_value": new_value}


def extract_change(event: "AnyEvent", listener: "Listener") -> tuple[str | None, str | None, str | None]:
    """The event's ``(entity_id, old_value, new_value)``; may raise on an unexpected payload shape.

    Values come from a state-change payload: the state, or the listener's tracked attribute.
    """
    payload = event.payload
    if not isinstance(payload, HassPayload):
        return None, None, None
    data = payload.data
    if not isinstance(data, RawStateChangePayload):
        return payload.entity_id, None, None
    attribute = listener.entity_watch.attribute if listener.entity_watch is not None else None
    return payload.entity_id, tracked_value(data.old_state, attribute), tracked_value(data.new_state, attribute)


def tracked_value(state: "HassStateDict | None", attribute: str | None) -> str | None:
    """The state value, or ``attribute`` under ``attributes``, as a capped display string.

    None when the state or attribute is missing; an explicit JSON null is ``"null"``.
    """
    if state is None:
        return None
    if attribute is None:
        value: Any = state.get("state", _MISSING)
    else:
        attributes = state.get("attributes") or {}
        value = attributes.get(attribute, _MISSING)
    if value is _MISSING:
        return None
    return format_trigger_value(value)


def format_trigger_value(value: Any) -> str:
    """Strings as-is, anything else as compact JSON; cut to ``TRIGGER_VALUE_MAX_CHARS`` with a trailing ``…``."""
    return format_display_value(value, TRIGGER_VALUE_MAX_CHARS)


def format_display_value(value: Any, max_chars: int) -> str:
    """Strings as-is, anything else as compact JSON; cut to ``max_chars`` code points with a trailing ``…``.

    ``default=str`` renders values JSON can't encode by their ``str()``, so a ``SecretStr`` stores masked.
    """
    text = (
        value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    )
    if len(text) <= max_chars:
        return text
    return text[: max_chars - len(TRUNCATION_MARK)] + TRUNCATION_MARK
