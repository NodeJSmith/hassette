"""Correlates outgoing WebSocket requests with their result replies.

Extracted from :mod:`hassette.core.websocket_service` to keep that file within the size
guideline. Owns the pending response futures for one connection and the bounded record of
timed-out non-retried sends, so a late reply to one of those can still be logged.
"""

import logging
import typing
from collections import OrderedDict
from contextlib import suppress
from typing import Any

from hassette.exceptions import FailedMessageError, RetryableConnectionClosedError

if typing.TYPE_CHECKING:
    import asyncio

# Most timed-out non-retried sends remembered at once, so a late reply can report whether the
# write later succeeded or whether Home Assistant reported failure. Oldest entries are evicted
# first; a reply arriving after eviction stays silent.
TIMED_OUT_WRITE_RECORD_CAP = 100


class PendingResponses:
    """Correlates outgoing WebSocket requests with their replies for one connection.

    Message ids are scoped to a single connection: both the pending-future mapping and the
    timed-out-write record are tied to the connection that issued them, and both are cleared
    whenever that connection is cleaned up or torn down.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger
        self.futures: dict[int, asyncio.Future[Any]] = {}
        self.timed_out_writes: OrderedDict[int, str] = OrderedDict()

    def register(self, msg_id: int, fut: "asyncio.Future[Any]") -> None:
        """Track ``fut`` as the response future for ``msg_id`` until it is discarded."""
        self.futures[msg_id] = fut

    def discard(self, msg_id: int) -> None:
        """Stop tracking the response future for ``msg_id``, if any."""
        self.futures.pop(msg_id, None)

    def respond_if_necessary(self, message: dict) -> None:
        """Resolve the future (or settle the timed-out-write record) for a 'result' message."""
        if message.get("type") != "result":
            return

        msg_id = message.get("id")

        if not msg_id:
            self.logger.warning("Received result message without ID: %s", message)
            return

        fut = self.futures.get(msg_id)
        if fut is None:
            self.settle_timed_out_write(msg_id, message)
            return
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

    def record_timed_out_write(self, msg_id: int, command_type: str) -> None:
        """Remember a timed-out non-retried send so a late reply can report its outcome."""
        self.timed_out_writes[msg_id] = command_type
        if len(self.timed_out_writes) > TIMED_OUT_WRITE_RECORD_CAP:
            self.timed_out_writes.popitem(last=False)

    def settle_timed_out_write(self, msg_id: int, message: dict) -> None:
        """Log a late reply to a timed-out non-retried send and drop its record.

        A late success proves the write applied. A late failure only reports that Home
        Assistant returned an error for it -- a call_service write (a script, a custom
        service) can partly apply before failing, so a failure reply does not prove the
        command had no effect.
        """
        command_type = self.timed_out_writes.pop(msg_id, None)
        if command_type is None:
            return
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

    def fail_all(self) -> None:
        """Fail every pending future with RetryableConnectionClosedError and clear all state.

        Suppresses exceptions from ``set_exception`` so this never blocks the caller's own
        cleanup, whether that caller is a reconnect-time partial cleanup or a full teardown.
        """
        for fut in list(self.futures.values()):
            if not fut.done():
                with suppress(Exception):
                    fut.set_exception(RetryableConnectionClosedError("WebSocket disconnected"))
        self.futures.clear()
        self.timed_out_writes.clear()
