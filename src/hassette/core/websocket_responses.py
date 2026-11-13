"""Correlates outgoing WebSocket requests with their result replies.

Extracted from :mod:`hassette.core.websocket_service` to keep that file within the size
guideline. Owns one table of sent requests per connection. An entry is awaited while a caller
waits on its future. It becomes a background entry when nobody waits on it: a fire-and-forget
write from registration, or a non-retried write whose caller stopped waiting (timeout or
cancellation). A background entry stays until its reply, the connection's end, or eviction.

An entry may carry a resolve callback, which owns the outcome of the API write record it was
registered for (design/specs/149-api-write-records D1): the reply, ``fail_all`` or eviction calls it
exactly once, and the entry leaves the table at the same moment.
"""

import logging
import time
import typing
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Protocol

from hassette_wire import ApiWriteOutcome

from hassette.core.pipeline_counters import PipelineCounter
from hassette.exceptions import CommandRejectedError, WebsocketClosedError
from hassette.utils.hass_utils import context_id_of

if typing.TYPE_CHECKING:
    import asyncio

    from hassette.core.pipeline_counters import PipelineCounters

BACKGROUND_ENTRY_CAP = 10_000
"""Most background entries (no caller waiting) kept at once. Each holds ids and a callback, not the
write's payload, so the cap bounds the table at about 2 MB. Past it, the earliest-sent background
entry is evicted: its write record resolves as ``unresolved`` and its reply is no longer recorded.
An entry whose caller is still waiting never counts toward the cap and is never evicted."""


class ResolveCallback(Protocol):
    """Resolves the API write record an entry was registered for.

    Called once, synchronously on the event loop: by the reply, ``fail_all``, or eviction.
    """

    # dup-ignore-start: ResolveCallback protocol signature restated by its implementation and its caller
    def __call__(
        self,
        outcome: ApiWriteOutcome,
        *,
        context_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None: ...

    # dup-ignore-end


@dataclass(slots=True)
class PendingReply:
    """One sent request's entry in the correlation table."""

    command_type: str
    future: "asyncio.Future[Any] | None" = None
    """The awaited caller's response future; None for a fire-and-forget write."""
    on_resolve: ResolveCallback | None = None
    """Resolves the write's record; None for an unrecorded request."""
    keep_when_abandoned: bool = False
    """Whether the entry stays to await its reply once its caller stops waiting: set for non-retried writes."""
    awaited: bool = True
    """Whether a caller still waits on ``future``. False makes this a background entry."""

    @property
    def fire_and_forget(self) -> bool:
        """Whether the call was sent without anyone ever waiting on it (no response future)."""
        return self.future is None


class PendingResponses:
    """Correlates outgoing WebSocket requests with their replies for one connection.

    Message ids are scoped to a single connection, so the table is cleared whenever that
    connection is cleaned up or torn down. An entry moves from awaited to background in one
    synchronous step (``release``), so no reply can arrive between the two states. Entries keep
    their registration (send) order: going to the background never reorders one.
    """

    def __init__(self, logger: logging.Logger, counters: "PipelineCounters", eviction_warn_interval: float) -> None:
        self.logger = logger
        self.entries: dict[int, PendingReply] = {}
        self.counters = counters
        self.eviction_warn_interval = eviction_warn_interval
        self.background_count = 0
        """Running count of background entries, so the cap check never rescans the table."""
        self.last_eviction_warn_ts: float | None = None

    def register(
        self,
        msg_id: int,
        fut: "asyncio.Future[Any]",
        command_type: str,
        *,
        on_resolve: ResolveCallback | None = None,
        keep_when_abandoned: bool = False,
    ) -> None:
        """Track ``fut`` as the awaited response future for ``msg_id``."""
        self.entries[msg_id] = PendingReply(
            command_type, fut, on_resolve=on_resolve, keep_when_abandoned=keep_when_abandoned
        )

    def register_fire_and_forget(self, msg_id: int, command_type: str, on_resolve: ResolveCallback) -> None:
        """Track a fire-and-forget write as a background entry, so its reply resolves its record."""
        self.entries[msg_id] = PendingReply(command_type, on_resolve=on_resolve, awaited=False)
        self.add_background()

    def discard(self, msg_id: int) -> None:
        """Stop tracking ``msg_id`` without resolving it: the request was never sent."""
        entry = self.entries.pop(msg_id, None)
        if entry is not None and not entry.awaited:
            self.background_count -= 1

    def release(self, msg_id: int) -> None:
        """Record that ``msg_id``'s caller stopped waiting: it timed out or was cancelled.

        A non-retried write stays as a background entry to await its reply; anything else leaves the table.
        A no-op when the reply already removed the entry (the caller got its answer).
        """
        entry = self.entries.get(msg_id)
        if entry is None or not entry.awaited:
            return
        if not entry.keep_when_abandoned:
            del self.entries[msg_id]
            return
        entry.awaited = False
        self.add_background()

    def add_background(self) -> None:
        """Count one more background entry, evicting the earliest-sent ones past the cap."""
        self.background_count += 1
        while self.background_count > BACKGROUND_ENTRY_CAP:
            # Awaited entries are the only ones skipped, and they number at most the callers waiting right now.
            msg_id = next(i for i, e in self.entries.items() if not e.awaited)
            entry = self.entries.pop(msg_id)
            self.background_count -= 1
            self.counters.increment(PipelineCounter.API_WRITE_TRACKING_EVICTED)
            self.warn_eviction()
            if entry.on_resolve is not None:
                self.run_callback(entry, "unresolved")

    def warn_eviction(self) -> None:
        """Log one WARNING per eviction episode, paced like the execution write queue's capacity WARNING."""
        now = time.monotonic()
        if self.last_eviction_warn_ts is not None and now - self.last_eviction_warn_ts < self.eviction_warn_interval:
            return
        self.last_eviction_warn_ts = now
        self.logger.warning(
            "More than %d sent writes are awaiting a Home Assistant reply; evicting the oldest, whose records "
            "read 'unresolved' (counted under %s)",
            BACKGROUND_ENTRY_CAP,
            PipelineCounter.API_WRITE_TRACKING_EVICTED.name,
        )

    def respond_if_necessary(self, message: dict) -> None:
        """Settle the entry a 'result' message answers: resolve its future and record, or log a late reply."""
        if message.get("type") != "result":
            return

        msg_id = message.get("id")

        if not msg_id:
            self.logger.warning("Received result message without ID: %s", message)
            return

        entry = self.entries.pop(msg_id, None)
        if entry is None:
            return
        if not entry.awaited:
            self.background_count -= 1

        success = bool(message.get("success"))
        error_envelope = {} if success else (message.get("error") or {})
        code = error_envelope.get("code")

        if entry.awaited and entry.future is not None and not entry.future.done():
            if success:
                entry.future.set_result(message.get("result"))
            else:
                entry.future.set_exception(self.rejection(message, error_envelope))
        elif not entry.fire_and_forget:
            self.log_late_reply(msg_id, entry.command_type, message)

        if entry.on_resolve is None:
            return
        if success:
            self.run_callback(entry, "success", context_id=context_id_of(message.get("result")))
        else:
            self.run_callback(
                entry,
                "rejected",
                error_code=None if code is None else str(code),
                error_message=error_envelope.get("message"),
            )

    def rejection(self, message: dict, error_envelope: dict) -> CommandRejectedError:
        """Build the exception an awaited caller gets for an error reply."""
        # HA error envelope shape (see design/specs/2037-helper-crud-api/design.md):
        #   {"type": "result", "success": false, "error": {"code": "<code>", "message": "<msg>"}}
        err = error_envelope.get("message", "Unknown error")
        code = error_envelope.get("code")
        if code is None and error_envelope:
            self.logger.debug(
                "HA error envelope has no 'code' field (raw envelope: %r). "
                "e.code will be None — caller code-guards will fall through.",
                error_envelope,
            )
        return CommandRejectedError.from_error_response(err, code=code, original_data=message)

    # dup-ignore-start: ResolveCallback protocol signature restated by its implementation and its caller
    def run_callback(
        self,
        entry: PendingReply,
        outcome: ApiWriteOutcome,
        *,
        context_id: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        # dup-ignore-end
        """Run ``entry``'s resolve callback, logging a failure so it never stops the caller's own work."""
        if entry.on_resolve is None:
            return
        try:
            entry.on_resolve(outcome, context_id=context_id, error_code=error_code, error_message=error_message)
        except Exception:
            self.logger.exception("Failed to record the %r outcome of a %r write", outcome, entry.command_type)

    def log_late_reply(self, msg_id: int, command_type: str, message: dict) -> None:
        """Log a late reply to a non-retried write whose caller stopped waiting.

        A late success proves the write applied. A late failure only reports that Home
        Assistant returned an error for it -- a call_service write (a script, a custom
        service) can partly apply before failing, so a failure reply does not prove the
        command had no effect.
        """
        if message.get("success"):
            self.logger.info(
                "Late reply to abandoned %r (id %s): it succeeded, so the command applied after its caller stopped "
                "waiting",
                command_type,
                msg_id,
            )
        else:
            code = (message.get("error") or {}).get("code")
            self.logger.warning(
                "Late reply to abandoned %r (id %s): Home Assistant reported failure (code %r); "
                "check state before re-sending",
                command_type,
                msg_id,
                code,
            )

    def fail_all(self, close_code: int | None = None) -> None:
        """Fail every awaited future with WebsocketClosedError, resolve every record as lost, and clear the table.

        ``close_code`` is the dropped socket's close code, carried onto each failure so the caller's
        ``ResponseLostError`` reports why the connection closed.

        Suppresses exceptions from ``set_exception`` (and logs callback failures) so this never blocks
        the caller's own cleanup, whether that caller is a reconnect-time partial cleanup or a full teardown.
        """
        entries = list(self.entries.values())
        self.entries.clear()
        self.background_count = 0
        for entry in entries:
            # A background entry's future has no awaiter left; failing it would only leave an
            # unretrieved exception behind.
            if entry.awaited and entry.future is not None and not entry.future.done():
                with suppress(Exception):
                    entry.future.set_exception(WebsocketClosedError("WebSocket disconnected", close_code=close_code))
            self.run_callback(entry, "connection_lost")


def command_label(data: dict[str, Any]) -> str:
    """Name a command by type and id only, for logs and error messages: payload values may be sensitive.

    Exceptions still carry the full payload on ``original_data`` for programmatic inspection.
    """
    return f"{data.get('type')!r} (id {data.get('id')})"
