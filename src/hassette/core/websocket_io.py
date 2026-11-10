"""Message send, receive, and inbound dispatch for :class:`~hassette.core.websocket_service.WebsocketService`.

Extracted from :mod:`hassette.core.websocket_service` to keep that file within the size
guideline. The mixin owns no connection state: it reads the socket, send gate, and
pending-responses table its host provides, and never transitions ``ConnectionState``.
"""

import asyncio
import logging
import typing
from contextlib import suppress
from logging import Logger
from typing import Any, cast

import aiohttp
from aiohttp import WSMsgType
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from hassette.core.ha_core_config import CORE_CONFIG_UPDATED_EVENT_TYPE
from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS, SINGLE_ATTEMPT
from hassette.core.websocket_inbound import log_dispatch_failure, parse_text_frame
from hassette.core.websocket_reconnect import CLOSE_MSG_TYPE_MESSAGES, HA_STARTED_EVENT_TYPE
from hassette.core.websocket_responses import PendingResponses, ResolveCallback, command_label
from hassette.events import RawStateChangeEvent, create_event_from_hass
from hassette.events.metadata import stamp_websocket_generation
from hassette.exceptions import (
    WS_NOT_CONNECTED_MESSAGE,
    CommandNotSentError,
    OutcomeUnknownError,
    ResponseLostError,
    ResponseTimeoutError,
    WebsocketClosedError,
)
from hassette.types.enums import ConnectionState

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events.hass.raw import HassEventEnvelopeDict
    from hassette.task_bucket import TaskBucket

RESPONSE_TIMEOUT_SECONDS = 15
"""Seconds to wait for a Home Assistant reply to a sent message.

Read at call time, so tests can force a timeout by monkeypatching it.
"""


class WebsocketMessageIOMixin:
    """Message send/receive/dispatch for ``WebsocketService``."""

    # Provided by the WebsocketService host (its own body or Resource);
    # declared here for type narrowing within the mixin.
    hassette: "Hassette"
    logger: Logger
    shutdown_event: asyncio.Event
    _ws: aiohttp.ClientWebSocketResponse | None
    _send_ready_event: asyncio.Event
    _pending: PendingResponses
    _connection_state: ConnectionState
    _core_started_event: asyncio.Event
    _held_started_event: "HassEventEnvelopeDict | None"
    task_bucket: "TaskBucket"

    _seq: typing.Iterator[int]
    """Iterator for generating unique message IDs."""

    if typing.TYPE_CHECKING:

        def get_connected_generation(self) -> int | None:
            """Return the active connection generation; provided by the host ``WebsocketService``."""
            ...

        async def refresh_ha_core_config(self) -> None:
            """Re-read Home Assistant's core config; provided by the host ``WebsocketService``."""
            ...

    def get_next_message_id(self) -> int:
        """Get the next message ID."""
        return next(self._seq)

    async def recv_loop(self) -> None:
        """Receive and dispatch frames until the socket closes.

        A connection close during shutdown ends the loop quietly; any other close is re-raised
        so the reconnect loop can handle it.
        """
        try:
            while True:
                await self.raw_recv()
        except WebsocketClosedError as exc:
            if not self.shutdown_event.is_set():
                raise
            self.logger.debug("Socket closed during shutdown, ending receive loop quietly: %s", exc)

    async def send_and_await_response(
        self,
        payload: dict[str, Any],
        msg_id: int,
        *,
        keep_when_abandoned: bool = False,
        on_resolve: ResolveCallback | None = None,
    ) -> Any:
        """Register a response future for msg_id, send payload, and await the reply.

        Registers the future before sending so a fast reply arriving before ``send_json``
        returns is never dropped. A send that fails (anything but cancellation) removes the
        entry unresolved, since no reply can come. When the caller stops waiting (a timeout or a
        cancellation) the entry leaves the table, unless ``keep_when_abandoned`` keeps it as a
        background entry until its reply or the connection's end.

        Args:
            payload: The JSON payload to send. Must already include ``"id": msg_id``.
            msg_id: The message id used to correlate the response future.
            keep_when_abandoned: Keep the entry once the caller stops waiting. Only for a
                non-retried write, whose late reply is logged and resolves ``on_resolve``.
            on_resolve: Resolves the write's API write record from the reply or ``fail_all``.

        Returns:
            The response payload once ``respond_if_necessary`` resolves the future.

        Raises:
            TimeoutError: If no response arrives within ``RESPONSE_TIMEOUT_SECONDS``.
        """
        fut = self.hassette.loop.create_future()
        self._pending.register(
            msg_id, fut, str(payload.get("type")), on_resolve=on_resolve, keep_when_abandoned=keep_when_abandoned
        )
        try:
            try:
                await self.send_json(**payload)
            except asyncio.CancelledError:
                # The frame may or may not have gone out, so this is a caller that stopped waiting:
                # release() below keeps the entry only if keep_when_abandoned is set.
                raise
            except Exception:
                self._pending.discard(msg_id)
                raise
            # asyncio.wait, unlike wait_for, never cancels fut. A reply landing after the deadline
            # but before this task resumes still resolves it and is returned below, and the
            # check-and-release in the finally has no await in it for a reply to slip into.
            await asyncio.wait({fut}, timeout=RESPONSE_TIMEOUT_SECONDS)
            if fut.done():
                return fut.result()
            raise TimeoutError
        finally:
            # A no-op once the reply removed the entry.
            self._pending.release(msg_id)

    async def send_fire_and_forget(self, on_resolve: ResolveCallback, **data: Any) -> None:
        """Send a write without waiting, tracking its reply in the background to resolve ``on_resolve``.

        The entry is registered before sending, so a reply arriving while ``send_json`` is still
        awaiting is never dropped. A send that fails (anything but cancellation) removes it unresolved.

        Raises:
            CommandNotSentError: As ``send_json``.
        """
        msg_id = self.get_next_message_id()
        data["id"] = msg_id
        self._pending.register_fire_and_forget(msg_id, str(data.get("type")), on_resolve)
        try:
            await self.send_json(**data)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._pending.discard(msg_id)
            raise

    async def subscribe_events(self, event_type: str | None = None) -> int:
        """Subscribe to HA events; returns the subscription ID HA confirmed.

        Handles its own retry loop (rather than delegating to send_and_wait) because
        subscribe_events has side effects: each send creates a real subscription on HA.
        Before each retry, the previous attempt's subscription is proactively unsubscribed
        in case HA processed it despite the timeout. If all retries exhaust, the final
        attempt's subscription is not cleaned up here — reconnect handles that case.
        """
        payload: dict[str, Any] = {"type": "subscribe_events"}
        if event_type is not None:
            payload["event_type"] = event_type

        last_abandoned_id: int | None = None

        @retry(
            retry=retry_if_exception(is_retryable_ws_failure),
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
            wait=wait_exponential_jitter(),
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
            reraise=True,
        )
        async def subscribe_with_retry() -> int:
            nonlocal last_abandoned_id
            if last_abandoned_id is not None:
                with suppress(Exception):
                    await self.send_json(
                        type="unsubscribe_events",
                        subscription=last_abandoned_id,
                        id=self.get_next_message_id(),
                    )

            msg_id = self.get_next_message_id()
            try:
                await self.send_and_await_response({**payload, "id": msg_id}, msg_id)
                return msg_id
            except TimeoutError:
                last_abandoned_id = msg_id
                raise ResponseTimeoutError(
                    f"subscribe_events response timed out after {RESPONSE_TIMEOUT_SECONDS}s",
                    original_data={**payload, "id": msg_id},
                ) from None

        return await subscribe_with_retry()

    async def send_and_wait(
        self, *, retry_on_timeout: bool = True, on_resolve: ResolveCallback | None = None, **data: Any
    ) -> dict[str, Any]:
        """Send a message and wait for a response.

        Retries only a response timeout (when ``retry_on_timeout`` allows), with exponential backoff.
        A not-sent, rejected, or lost command is raised at once. After retries the raised class
        describes the last attempt only: a ``CommandNotSentError`` after an earlier timeout doesn't
        prove the command never reached Home Assistant, which is one more reason writes pass
        ``retry_on_timeout=False``.

        Shares ``send_json``'s gate: it requires an authenticated socket, not external readiness.
        Callers that must wait for CONNECTED check ``is_connected`` first.

        Args:
            retry_on_timeout: Whether a response timeout may be retried. Defaults to True.
                A retry re-sends the payload under a fresh message id, so Home Assistant applies
                the command again. That is safe for reads, but duplicates the side effect of a
                command Home Assistant already applied before its response envelope was lost.
                Callers sending a non-idempotent command must pass False and accept a
                ``ResponseTimeoutError`` on the first timeout. (``subscribe_events`` solves the same
                problem with its own retry loop, which unsubscribes the abandoned attempt.)
            on_resolve: Resolves the write's API write record from its reply or the connection's end.
                Only with ``retry_on_timeout=False``, so the record covers exactly one sent command.
            **data: The data to send as a JSON payload. ``retry_on_timeout`` and ``on_resolve`` are
                client-side and consumed here, so they cannot double as payload field names.

        Returns:
            The response data from the WebSocket.

        Raises:
            ResponseTimeoutError: If no response arrived in time (after all retries, if retried).
                The command may or may not have applied.
            ResponseLostError: If the connection dropped while waiting. Never retried; the
                command may or may not have applied.
            CommandNotSentError: If the send gate is closed or the socket write failed. Never retried.
            CommandRejectedError: If Home Assistant answered with an error. Never retried.
        """
        if on_resolve is not None and retry_on_timeout:
            raise ValueError("on_resolve needs retry_on_timeout=False: a recorded write is sent exactly once")
        caller_id = data.pop("id", None)

        @retry(
            retry=retry_if_exception(is_retryable_ws_failure),
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS if retry_on_timeout else SINGLE_ATTEMPT),
            wait=wait_exponential_jitter(),
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
            reraise=True,
        )
        async def send_with_retry() -> dict[str, Any]:
            nonlocal caller_id
            if caller_id is not None:
                attempt_id = caller_id
                caller_id = None
            else:
                attempt_id = self.get_next_message_id()
            data["id"] = attempt_id

            try:
                return await self.send_and_await_response(
                    data, attempt_id, keep_when_abandoned=not retry_on_timeout, on_resolve=on_resolve
                )
            except TimeoutError:
                raise ResponseTimeoutError(
                    f"{command_label(data)}: no response within {RESPONSE_TIMEOUT_SECONDS}s; "
                    "the command may or may not have applied",
                    original_data=dict(data),
                ) from None
            except WebsocketClosedError as exc:
                raise ResponseLostError(
                    f"{command_label(data)}: connection lost while waiting for a response; "
                    "the command may or may not have applied",
                    close_code=exc.close_code,
                ) from exc

        try:
            return await send_with_retry()
        except OutcomeUnknownError as exc:
            self.logger.warning("%s", exc)
            raise

    def respond_if_necessary(self, message: dict) -> None:
        """Settle the pending entry ``message`` answers (see ``PendingResponses.respond_if_necessary``)."""
        self._pending.respond_if_necessary(message)

    async def send_json(self, **data: Any) -> None:
        """Send a JSON message over the socket without waiting for a response.

        Gated only on the send gate (authenticated socket with a running recv loop), not on
        external readiness: ``subscribe_events`` sends through here before CONNECTED is
        advertised. Callers that must wait for CONNECTED check ``is_connected`` first.

        Args:
            **data: The JSON payload. An ``id`` is assigned if not provided.

        Raises:
            CommandNotSentError: If the send gate is closed, or the socket write failed with a
                connection error. Any other exception from the write (such as a ``TypeError`` for a
                payload that can't be serialized) propagates unwrapped.
        """
        if not self._send_ready_event.is_set():
            raise CommandNotSentError(WS_NOT_CONNECTED_MESSAGE)

        # The send gate is only opened after authentication assigns the socket.
        if self._ws is None:
            raise RuntimeError("WebSocket must be initialized before sending messages")

        if "id" not in data:
            data["id"] = self.get_next_message_id()

        label = command_label(data)
        self.logger.debug("Sending WebSocket message %s", label)

        try:
            await self._ws.send_json(data)
        except ConnectionError as exc:
            # Covers aiohttp's ClientConnectionResetError (closing transport, before the write) and the
            # plain ConnectionError a lost connection sets on the drain wait (after it). The second
            # may have sent the frame; CommandNotSentError's docstring states that edge case.
            self.logger.error("WebSocket connection lost while sending message %s", label)
            raise CommandNotSentError(f"{label}: not sent, the WebSocket connection was lost") from exc
        except Exception:
            self.logger.exception("Exception when sending message %s", label)
            raise

    async def raw_recv(self) -> None:
        """Receive a raw WebSocket frame.

        Raises:
            WebsocketClosedError: If the connection is closed.
        """
        if not self._ws:
            raise RuntimeError(WS_NOT_CONNECTED_MESSAGE)

        if self._ws.closed:
            raise WebsocketClosedError("WebSocket connection is closed")

        msg = await self._ws.receive()
        msg_type, raw = msg.type, msg.data

        if msg_type == WSMsgType.TEXT:
            if (data := parse_text_frame(raw, self.logger)) is not None:
                await self.dispatch(data)
            return

        if msg_type == WSMsgType.BINARY:
            self.logger.warning("Received unexpected binary message (%d bytes)", len(raw))
            return

        if (message := CLOSE_MSG_TYPE_MESSAGES.get(msg_type)) is not None:
            close_code = getattr(self._ws, "close_code", None)
            raise WebsocketClosedError(f"{message} ({msg_type!r})", close_code=close_code)

        if msg_type == WSMsgType.ERROR:
            exc = msg.data if isinstance(msg.data, BaseException) else None
            close_code = getattr(self._ws, "close_code", None)
            raise WebsocketClosedError(f"WebSocket error frame received: {msg.data!r}", close_code=close_code) from exc

        self.logger.warning("Received unexpected message type: %r", msg_type)

    async def dispatch(self, data: dict[str, Any]) -> None:
        """Route a decoded message by ``type``: events go to the bus, results resolve pending requests.

        Unknown types are logged at DEBUG and ignored. Exceptions are logged rather than raised,
        so one bad message cannot end the receive loop.
        """
        try:
            match data.get("type"):
                case "event":
                    await self.dispatch_hass_event(cast("HassEventEnvelopeDict", data))
                case "result":
                    self.respond_if_necessary(data)
                case other:
                    self.logger.debug("Ignoring unknown message type: %s", other)
        except Exception as exc:
            log_dispatch_failure(self.logger, data, exc)

    async def dispatch_hass_event(self, data: "HassEventEnvelopeDict") -> None:
        """Dispatch a Home Assistant event to the event bus, once the connection is CONNECTED.

        Before CONNECTED (HA still booting, D12) events are dropped unstamped: the resync at
        CONNECTED replaces whatever they carried. ``homeassistant_started`` ends
        ``wait_for_core_running``'s wait and is held for ``mark_connected`` to dispatch.
        ``core_config_updated`` also starts a re-read of ``get_config`` in a framework task.
        """
        if self._connection_state != ConnectionState.CONNECTED:
            if (data.get("event") or {}).get("event_type") == HA_STARTED_EVENT_TYPE:
                self._held_started_event = data
                self._core_started_event.set()
            return

        event = create_event_from_hass(data)
        if isinstance(event, RawStateChangeEvent):
            stamp_websocket_generation(event, self.get_connected_generation())
        await self.hassette.send_event(event)

        if (data.get("event") or {}).get("event_type") == CORE_CONFIG_UPDATED_EVENT_TYPE:
            self.task_bucket.spawn(self.refresh_ha_core_config(), name="ws:refresh_core_config")


def is_retryable_ws_failure(exc: BaseException) -> bool:
    """Return whether a failed WebSocket attempt may be sent again: only a response timeout.

    Retry follows delivery state. A not-sent command means the connection just dropped (reconnect
    is the recovery), a rejected one would be refused again, and a lost one may already have applied.
    """
    return isinstance(exc, ResponseTimeoutError)
