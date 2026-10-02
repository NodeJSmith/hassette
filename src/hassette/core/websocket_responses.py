"""Correlates outgoing WebSocket requests with their result replies.

Extracted from :mod:`hassette.core.websocket_service` to keep that file within the size
guideline. Owns one table of sent requests per connection. Each entry is either awaiting its
reply or, for a non-retried write whose caller stopped waiting at the timeout, awaiting a late
reply that only gets logged.
"""

import logging
import typing
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any

from hassette.exceptions import FailedMessageError, RetryableConnectionClosedError

if typing.TYPE_CHECKING:
    import asyncio

# Most timed-out non-retried writes kept awaiting a late reply at once, so the reply can report
# whether the write later succeeded or whether Home Assistant reported failure. Oldest entries
# are evicted first; a reply arriving after eviction stays silent.
TIMED_OUT_WRITE_RECORD_CAP = 100


@dataclass(frozen=True)
class PendingReply:
    """One sent request's entry in the correlation table."""

    future: "asyncio.Future[Any]"
    timed_out_command: str | None = None
    """Command type of a non-retried write whose caller gave up at the timeout; None while awaited."""


class PendingResponses:
    """Correlates outgoing WebSocket requests with their replies for one connection.

    Message ids are scoped to a single connection, so the table is cleared whenever that
    connection is cleaned up or torn down. A request moves from awaited to timed out in one
    synchronous step (``mark_timed_out``), so no reply can arrive between the two states.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.entries: dict[int, PendingReply] = {}

    def register(self, msg_id: int, fut: "asyncio.Future[Any]") -> None:
        """Track ``fut`` as the response future for ``msg_id`` until it is discarded."""
        self.entries[msg_id] = PendingReply(fut)

    def discard(self, msg_id: int) -> None:
        """Stop tracking ``msg_id`` unless it was marked timed out to await a late reply."""
        entry = self.entries.get(msg_id)
        if entry is not None and entry.timed_out_command is None:
            del self.entries[msg_id]

    def mark_timed_out(self, msg_id: int, command_type: str) -> None:
        """Keep a timed-out non-retried write in the table so a late reply can report its outcome."""
        # Re-inserting moves the entry to the end, so timed-out entries sit in timeout order.
        entry = self.entries.pop(msg_id)
        self.entries[msg_id] = replace(entry, timed_out_command=command_type)
        # The table only ever holds in-flight requests plus at most the cap's worth of timed-out
        # writes, so scanning all of it is cheap.
        timed_out = [i for i, e in self.entries.items() if e.timed_out_command is not None]
        for evicted in timed_out[:-TIMED_OUT_WRITE_RECORD_CAP]:
            del self.entries[evicted]

    def respond_if_necessary(self, message: dict) -> None:
        """Resolve the awaited future, or log the late reply to a timed-out write, for a 'result' message."""
        if message.get("type") != "result":
            return

        msg_id = message.get("id")

        if not msg_id:
            self.logger.warning("Received result message without ID: %s", message)
            return

        entry = self.entries.get(msg_id)
        if entry is None:
            return
        if entry.timed_out_command is not None:
            del self.entries[msg_id]
            self.log_late_reply(msg_id, entry.timed_out_command, message)
            return
        fut = entry.future
        if fut.done():
            return

        if message.get("success"):
            fut.set_result(message.get("result"))
        else:
            # HA error envelope shape (see design/specs/2037-helper-crud-api/design.md):
            #   {"type": "result", "success": false, "error": {"code": "<code>", "message": "<msg>"}}
            error_envelope = message.get("error") or {}
            err = error_envelope.get("message", "Unknown error")
            code = error_envelope.get("code")
            if code is None and error_envelope:
                self.logger.debug(
                    "HA error envelope has no 'code' field (raw envelope: %r). "
                    "e.code will be None — caller code-guards will fall through.",
                    error_envelope,
                )
            fut.set_exception(FailedMessageError.from_error_response(err, code=code, original_data=message))

    def log_late_reply(self, msg_id: int, command_type: str, message: dict) -> None:
        """Log a late reply to a timed-out non-retried write.

        A late success proves the write applied. A late failure only reports that Home
        Assistant returned an error for it -- a call_service write (a script, a custom
        service) can partly apply before failing, so a failure reply does not prove the
        command had no effect.
        """
        if message.get("success"):
            self.logger.info(
                "Late reply to timed-out %r (id %s): it succeeded, so the command applied after the timeout",
                command_type,
                msg_id,
            )
        else:
            code = (message.get("error") or {}).get("code")
            self.logger.warning(
                "Late reply to timed-out %r (id %s): Home Assistant reported failure (code %r); "
                "check state before re-sending",
                command_type,
                msg_id,
                code,
            )

    def fail_all(self, close_code: int | None = None) -> None:
        """Fail every awaited future with RetryableConnectionClosedError and clear the table.

        ``close_code`` is the dropped socket's close code, carried onto each failure so the caller's
        ``ResponseLostError`` reports why the connection closed.

        Suppresses exceptions from ``set_exception`` so this never blocks the caller's own
        cleanup, whether that caller is a reconnect-time partial cleanup or a full teardown.
        """
        for entry in list(self.entries.values()):
            # A timed-out entry's future has no awaiter left; failing it would only leave an
            # unretrieved exception behind.
            if entry.timed_out_command is None and not entry.future.done():
                with suppress(Exception):
                    entry.future.set_exception(
                        RetryableConnectionClosedError("WebSocket disconnected", close_code=close_code)
                    )
        self.entries.clear()
