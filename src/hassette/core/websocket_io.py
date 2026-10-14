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
from aiohttp.client_exceptions import ClientConnectionResetError
from tenacity import before_sleep_log, retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS, SINGLE_ATTEMPT
from hassette.core.websocket_inbound import log_dispatch_failure, parse_text_frame
from hassette.core.websocket_reconnect import CLOSE_MSG_TYPE_MESSAGES, HA_STARTED_EVENT_TYPE
from hassette.core.websocket_responses import PendingResponses, command_label
from hassette.events import RawStateChangeEvent, create_event_from_hass
from hassette.events.metadata import stamp_websocket_generation
from hassette.exceptions import (
    WS_NOT_CONNECTED_MESSAGE,
    ConnectionClosedError,
    FailedMessageError,
    OutcomeUnknownError,
    ResponseLostError,
    ResponseTimeoutError,
    RetryableConnectionClosedError,
)
from hassette.types.enums import ConnectionState

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events.hass.raw import HassEventEnvelopeDict


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

    _seq: typing.Iterator[int]
    """Iterator for generating unique message IDs."""

    if typing.TYPE_CHECKING:

        def get_connected_generation(self) -> int | None: ...

    def get_next_message_id(self) -> int:
        """Get the next message ID."""
        return next(self._seq)

    @property
    def resp_timeout_seconds(self) -> int:
        return self.hassette.config.websocket.response_timeout_seconds

    async def recv_loop(self) -> None:
        try:
            while True:
                await self.raw_recv()
        except RetryableConnectionClosedError as exc:
            if not self.shutdown_event.is_set():
                raise
            self.logger.debug("Socket closed during shutdown, ending receive loop quietly: %s", exc)

    async def send_and_await_response(
        self,
        payload: dict[str, Any],
        msg_id: int,
        *,
        late_reply_command: str | None = None,
    ) -> Any:
        """Register a response future for msg_id, send payload, and await the reply.

        Registers the future before sending so a fast reply arriving before ``send_json``
        returns is never dropped. On exit the entry leaves the pending-responses table, except
        that a timeout with ``late_reply_command`` set keeps it there, marked timed out.

        Args:
            payload: The JSON payload to send. Must already include ``"id": msg_id``.
            msg_id: The message id used to correlate the response future.
            late_reply_command: Command type to log a late reply under if this times out. Only
                for a non-retried write; None drops the entry on timeout like any other exit.

        Returns:
            The response payload once ``respond_if_necessary`` resolves the future.

        Raises:
            TimeoutError: If no response arrives within ``resp_timeout_seconds``.
        """
        fut = self.hassette.loop.create_future()
        self._pending.register(msg_id, fut)
        try:
            await self.send_json(**payload)
            # asyncio.wait, unlike wait_for, never cancels fut. A reply landing after the deadline
            # but before this task resumes still resolves it and is returned below, and the
            # check-and-mark that follows has no await in it for a reply to slip into.
            await asyncio.wait({fut}, timeout=self.resp_timeout_seconds)
            if fut.done():
                return fut.result()
            if late_reply_command is not None:
                self._pending.mark_timed_out(msg_id, late_reply_command)
            raise TimeoutError
        finally:
            # A no-op for an entry just marked timed out: that one stays to await its late reply.
            self._pending.discard(msg_id)

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
            retry=retry_if_exception(lambda e: isinstance(e, FailedMessageError) and e.code is None),
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
                raise FailedMessageError(
                    f"subscribe_events response timed out after {self.resp_timeout_seconds}s"
                ) from None

        return await subscribe_with_retry()

    async def send_and_wait(self, *, retry_on_timeout: bool = True, **data: Any) -> dict[str, Any]:
        """Send a message and wait for a response.

        Retries on transient failures (timeouts) with exponential backoff,
        matching the retry behavior of the REST API layer.

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
            **data: The data to send as a JSON payload. ``retry_on_timeout`` is client-side
                policy and is consumed here, so it cannot double as a payload field name.

        Returns:
            The response data from the WebSocket.

        Raises:
            ResponseTimeoutError: If no response arrived in time (after all retries, if retried).
                The command may or may not have applied.
            ResponseLostError: If the connection dropped while waiting. Never retried; the
                command may or may not have applied.
            FailedMessageError: If Home Assistant rejected the command, or sending it failed
                after all retries.
        """
        caller_id = data.pop("id", None)
        command_type = str(data.get("type"))
        late_reply_command = None if retry_on_timeout else command_type

        @retry(
            retry=retry_if_exception(lambda e: isinstance(e, FailedMessageError) and e.code is None),
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
                return await self.send_and_await_response(data, attempt_id, late_reply_command=late_reply_command)
            except TimeoutError:
                raise ResponseTimeoutError(
                    f"{command_label(data)}: no response within {self.resp_timeout_seconds}s; "
                    "the command may or may not have applied",
                    original_data=dict(data),
                ) from None
            except RetryableConnectionClosedError as exc:
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
        """Resolve a pending response future (or log a late reply to a timed-out write) for ``message``."""
        self._pending.respond_if_necessary(message)

    async def send_json(self, **data: Any) -> None:
        """Send a JSON message over the socket without waiting for a response.

        Gated only on the send gate (authenticated socket with a running recv loop), not on
        external readiness: ``subscribe_events`` sends through here before CONNECTED is
        advertised. Callers that must wait for CONNECTED check ``is_connected`` first.

        Args:
            **data: The JSON payload. An ``id`` is assigned if not provided.

        Raises:
            ConnectionClosedError: If the send gate is closed.
            FailedMessageError: If writing to the socket failed.
        """
        if not self._send_ready_event.is_set():
            raise ConnectionClosedError(WS_NOT_CONNECTED_MESSAGE)

        # The send gate is only opened after authentication assigns the socket.
        assert self._ws is not None, "WebSocket must be initialized before sending messages"

        if "id" not in data:
            data["id"] = self.get_next_message_id()

        label = command_label(data)
        self.logger.debug("Sending WebSocket message %s", label)

        try:
            await self._ws.send_json(data)
        except ClientConnectionResetError:
            self.logger.error("WebSocket connection reset by peer while sending message %s", label)
            raise
        except Exception as exc:
            self.logger.exception("Exception when sending message %s", label)
            raise FailedMessageError(f"Failed to send message {label}", original_data=dict(data)) from exc

    async def raw_recv(self) -> None:
        """Receive a raw WebSocket frame.

        Raises:
            ConnectionClosedError: If the connection is closed.
        """
        if not self._ws:
            raise RuntimeError(WS_NOT_CONNECTED_MESSAGE)

        if self._ws.closed:
            raise RetryableConnectionClosedError("WebSocket connection is closed")

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
            raise RetryableConnectionClosedError(f"{message} ({msg_type!r})", close_code=close_code)

        if msg_type == WSMsgType.ERROR:
            exc = msg.data if isinstance(msg.data, BaseException) else None
            close_code = getattr(self._ws, "close_code", None)
            raise RetryableConnectionClosedError(
                f"WebSocket error frame received: {msg.data!r}", close_code=close_code
            ) from exc

        self.logger.warning("Received unexpected message type: %r", msg_type)

    async def dispatch(self, data: dict[str, Any]) -> None:
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
