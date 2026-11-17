"""Decoding and failure logging for inbound Home Assistant WebSocket messages.

Inbound frames are HA data and can carry sensitive values (helper `initial`, entity attributes), and
exception messages raised while handling them can quote those values (e.g. a pydantic `input_value`).
Every log line here therefore names only lengths, types, message ids, and traceback frames -- never
frame contents or `str(exc)`.
"""

import json
import logging
import traceback
from typing import Any

from hassette.core.websocket_responses import command_label
from hassette.events.hass.hass import MissingPayloadFieldsError


def parse_text_frame(raw: str, logger: logging.Logger) -> dict[str, Any] | None:
    """Decode a TEXT frame into a message dict, or log why it can't be dispatched and return None."""
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        # A JSONDecodeError message names only a position, so the traceback is safe to log.
        logger.exception("Invalid JSON received (%d chars)", len(raw))
        return None

    if not isinstance(data, dict):
        logger.warning("Non-object JSON received (%s, %d chars)", type(data).__name__, len(raw))
        return None

    return data


def log_dispatch_failure(logger: logging.Logger, data: dict[str, Any], exc: Exception) -> None:
    """Log a failed dispatch with the message's command label, exception type, and traceback frames.

    An event also names its HA event type, and a payload that lacks required fields names them: both are
    metadata, not values. `logger.exception`/`exc_info` would render `str(exc)`, hence the hand-built traceback.
    """
    label = command_label(data)
    event_type = (data.get("event") or {}).get("event_type") if data.get("type") == "event" else None
    if event_type:
        label = f"{label} event_type={event_type!r}"
    reason = type(exc).__name__
    if isinstance(exc, MissingPayloadFieldsError):
        reason = f"{reason}: {exc.payload} is missing required field(s) {', '.join(exc.missing)}"
    logger.error(
        "Failed to dispatch message %s: %s\nTraceback (most recent call last):\n%s",
        label,
        reason,
        "".join(traceback.format_tb(exc.__traceback__)).rstrip(),
    )
