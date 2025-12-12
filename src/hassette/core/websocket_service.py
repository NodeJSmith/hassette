import asyncio
import json
import logging
import typing
from contextlib import AsyncExitStack, suppress
from itertools import count
from logging import getLogger
from typing import Any, cast

import aiohttp
import anyio
from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from hassette.events import HassetteSimpleEvent, create_event_from_hass
from hassette.exceptions import (
    ConnectionClosedError,
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    ResourceNotReadyError,
    RetryableConnectionClosedError,
)
from hassette.resources.base import Service
from hassette.types import Topic

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events.hass.raw import HassEventEnvelopeDict

LOGGER = getLogger(__name__)

# classify errors once (easy to audit/change later)
NON_RETRYABLE = (InvalidAuthError, asyncio.CancelledError)
RETRYABLE = (
    RetryableConnectionClosedError,
    ServerDisconnectedError,
    ClientConnectorError,
    ClientOSError,
    CouldNotFindHomeAssistantError,
)


class WebsocketService(Service):
    url: str
    """WebSocket URL to connect to."""

    _stack: AsyncExitStack
    """Async context stack for managing resources."""

    _session: aiohttp.ClientSession | None
    """HTTP client session for making requests."""

    _ws: aiohttp.ClientWebSocketResponse | None
    """WebSocket connection."""

    _response_futures: dict[int, asyncio.Future[Any]]
    """Mapping of message IDs to futures for awaiting responses."""

    _seq: typing.Iterator[int]
    """Iterator for generating unique message IDs."""

    _recv_task: asyncio.Task | None
    """Task for receiving messages from the WebSocket."""

    _subscription_ids: set[int]
    """Set of active subscription IDs."""

    _connect_lock: asyncio.Lock
    """Lock to prevent concurrent connection attempts."""

    @classmethod
    def create(cls, hassette: "Hassette"):
        inst = cls(hassette=hassette, parent=hassette)
        inst.url = inst.hassette.ws_url
        inst._stack = AsyncExitStack()
        inst._session = None
        inst._ws = None
        inst._response_futures = {}
        inst._seq = count(1)

        inst._recv_task = None
        inst._subscription_ids = set()
        inst._connect_lock = asyncio.Lock()  # if you don't already have it
        return inst

    @property
    def config_log_level(self):
        """Return the log level from the config for this resource."""
        return self.hassette.config.websocket_log_level

    @property
    def resp_timeout_seconds(self) -> int:
        return self.hassette.config.websocket_response_timeout_seconds

    @property
    def connection_timeout_seconds(self) -> int:
        return self.hassette.config.websocket_connection_timeout_seconds

    @property
    def total_timeout_seconds(self) -> int:
        return self.hassette.config.websocket_total_timeout_seconds

    @property
    def heartbeat_interval_seconds(self) -> int:
        return self.hassette.config.websocket_heartbeat_interval_seconds

    @property
    def authentication_timeout_seconds(self) -> int:
        return self.hassette.config.websocket_authentication_timeout_seconds

    @property
    def connected(self) -> bool:
        if self._ws is None:
            return False

        if self._ws._conn is None:
            return False

        return not self._ws._conn.closed

    def get_next_message_id(self) -> int:
        """Get the next message ID."""
        return next(self._seq)

    async def before_shutdown(self) -> None:
        await self._send_connection_lost_event()

    async def serve(self) -> None:
        """Connect to the WebSocket and run the receive loop."""
        async with self._connect_lock:
            timeout = ClientTimeout(connect=self.connection_timeout_seconds, total=self.total_timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                self._recv_task = await self._make_connection(session)

                # Keep running until recv loop ends (disconnect, error, etc.)
                await self._recv_task

    async def _make_connection(self, session: aiohttp.ClientSession) -> asyncio.Task:
        # inner function so we can use `self` in the retry decorator
        @retry(
            retry=retry_if_not_exception_type(NON_RETRYABLE) | retry_if_exception_type(RETRYABLE),
            wait=wait_exponential_jitter(initial=1, max=32),
            stop=stop_after_attempt(5),
            reraise=True,
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
        )
        async def _inner_connect():
            self._session = session

            try:
                self._ws = await session.ws_connect(
                    self.url, heartbeat=self.heartbeat_interval_seconds, ssl=self.hassette.config.verify_ssl
                )
            except ClientConnectorError as exc:
                if exc.__cause__ and isinstance(exc.__cause__, ConnectionRefusedError):
                    raise CouldNotFindHomeAssistantError(self.url) from exc.__cause__
                raise

            self.logger.debug("Connected to WebSocket at %s", self.url)
            await self.authenticate()

            # mark ready before subscribing, otherwise we'll raise an exception due to not ready status
            self.mark_ready(reason="WebSocket connected and authenticated")

            # start reader first so send_and_wait can get replies
            recv_task = self.task_bucket.spawn(self._recv_loop(), name="ws:recv")

            await self._send_connection_established_event()
            # subscribe to events
            self._subscription_ids.add(await self._subscribe_events())
            return recv_task

        return await _inner_connect()

    async def _recv_loop(self) -> None:
        while True:
            await self._raw_recv()

    async def _subscribe_events(self, event_type: str | None = None) -> int:
        """Subscribe to HA events; returns the subscription ID (the message id you sent)."""
        payload: dict[str, Any] = {"type": "subscribe_events"}
        if event_type is not None:
            payload["event_type"] = event_type  # omit to get all events

        payload["id"] = sub_id = self.get_next_message_id()
        # Use send_and_wait so we see success/error deterministically
        await self.send_and_wait(**payload)
        # HA replies with {'id': <same>, 'type': 'result', 'success': True}
        # We return our own id as the subscription handle for unsubscribe
        return sub_id

    async def cleanup(self) -> None:
        """Cleanup resources after the WebSocket connection is closed."""

        # Set exceptions for all pending response futures
        for fut in list(self._response_futures.values()):
            if not fut.done():
                fut.set_exception(RetryableConnectionClosedError("WebSocket disconnected"))
        self._response_futures.clear()

        # Try to unsubscribe (best-effort; ignore errors if socket is going away)
        if self._ws and not self._ws.closed and self._subscription_ids:
            for sid in list(self._subscription_ids):
                with suppress(Exception):
                    await self.send_json(type="unsubscribe_events", subscription=sid)
            self._subscription_ids.clear()

        # Stop the recv loop
        if self._recv_task:
            self._recv_task.cancel()
            await asyncio.gather(self._recv_task, return_exceptions=True)
            self._recv_task = None

        # Close the WebSocket
        if self._ws and not self._ws.closed:
            await self._ws.close(
                code=aiohttp.WSCloseCode.GOING_AWAY,
                message=b"Shutting down WebSocket connection",
            )
            self.logger.debug("Closed WebSocket with code %s", aiohttp.WSCloseCode.GOING_AWAY)

        # Close the aiohttp session
        if self._session:
            await self._session.close()
            self.logger.debug("Closed aiohttp session")

        await super().cleanup()

    async def send_and_wait(self, **data: Any) -> dict[str, Any]:
        """Send a message and wait for a response.

        Args:
            **data: The data to send as a JSON payload.

        Returns:
            The response data from the WebSocket.

        Raises:
            FailedMessageError: If sending the message fails or times out.
        """

        if "id" not in data:
            data["id"] = msg_id = self.get_next_message_id()
        else:
            msg_id = data["id"]

        fut = self.hassette.loop.create_future()
        self._response_futures[msg_id] = fut
        try:
            await self.send_json(**data)
            return await asyncio.wait_for(fut, timeout=self.resp_timeout_seconds)
        except TimeoutError:
            raise FailedMessageError(f"Response timed out after {self.resp_timeout_seconds}s (data: {data})") from None
        finally:
            self._response_futures.pop(msg_id, None)

    def _respond_if_necessary(self, message: dict) -> None:
        if message.get("type") != "result":
            return

        msg_id = message.get("id")

        if not msg_id:
            self.logger.warning("Received result message without ID: %s", message)
            return

        fut = self._response_futures.get(msg_id)
        if not fut or fut.done():
            return

        if message.get("success"):
            fut.set_result(message.get("result"))

        else:
            err = (message.get("error") or {}).get("message", "Unknown error")
            fut.set_exception(FailedMessageError.from_error_response(err, original_data=message))

    async def send_json(self, **data) -> None:
        """Send a JSON payload over the WebSocket connection, with an incrementing message ID.

        Args:
            **data: The data to send as a JSON payload.

        Raises:
            FailedMessageError: If sending the message fails.
        """

        if not self.ready_event.is_set():
            raise ResourceNotReadyError("WebSocket is not ready")

        self.logger.debug("Sending WebSocket message: %s", data)

        if not isinstance(data, dict):
            raise TypeError("Payload must be a dictionary, got %s", type(data).__name__)

        if not self.connected:
            raise ConnectionClosedError("WebSocket connection is not established")

        # this should never be an issue because self.connected checks for this already
        assert self._ws is not None, "WebSocket must be initialized before sending messages"

        if "id" not in data:
            data["id"] = self.get_next_message_id()

        try:
            await self._ws.send_json(data)
        except ClientConnectionResetError:
            self.logger.error("WebSocket connection reset by peer")
            raise

        except Exception as e:
            self.logger.exception("Exception when sending message: %s", data)
            raise FailedMessageError(f"Failed to send message: {data}") from e

    async def authenticate(self) -> None:
        """Authenticate with the Home Assistant WebSocket API."""

        assert self._ws, "WebSocket must be initialized before authenticating"
        token = self.hassette.config.token
        truncated_token = self.hassette.config.truncated_token
        ws_url = self.hassette.ws_url

        with anyio.fail_after(self.authentication_timeout_seconds):
            msg = await self._ws.receive_json()
            assert msg["type"] == "auth_required"
            await self._ws.send_json({"type": "auth", "access_token": token})
            msg = await self._ws.receive_json()

            # happy path
            if msg["type"] == "auth_ok":
                self.logger.debug("Authenticated successfully with Home Assistant at %s", ws_url)
                return

            if msg["type"] == "auth_invalid":
                self.logger.critical(
                    "Invalid authentication (using token %s) for Home Assistant instance at %s",
                    truncated_token,
                    ws_url,
                )
                raise InvalidAuthError(f"Authentication failed - invalid access token ({truncated_token}) for {ws_url}")

            raise RuntimeError(f"Unexpected authentication response: {msg}")

    async def _raw_recv(self) -> None:
        """Receive a raw WebSocket frame.

        Raises:
            ConnectionClosedError: If the connection is closed.
        """

        if not self._ws:
            raise RuntimeError("WebSocket connection is not established")

        if self._ws.closed:
            raise RetryableConnectionClosedError("WebSocket connection is closed")

        msg = await self._ws.receive()
        msg_type, raw = msg.type, msg.data

        if msg_type == WSMsgType.TEXT:
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                self.logger.exception("Invalid JSON received: %s", raw)
                return

            await self._dispatch(data)
            return

        if msg_type == WSMsgType.BINARY:
            self.logger.warning("Received binary message, which is not expected: %r", raw)
            return

        if msg_type in {WSMsgType.CLOSE, WSMsgType.CLOSED}:
            raise RetryableConnectionClosedError(f"WebSocket closed by peer ({msg_type!r})")

        # took a while to track this one down - we need to cancel if we get told that the connection is closing
        if msg_type == WSMsgType.CLOSING:
            self.logger.debug("WebSocket is closing - exiting receive loop")
            raise RetryableConnectionClosedError("WebSocket is closing")

        self.logger.warning("Received unexpected message type: %r", msg_type)

    async def _dispatch(self, data: dict[str, Any]) -> None:
        try:
            match data.get("type"):
                case "event":
                    await self._dispatch_hass_event(cast("HassEventEnvelopeDict", data))
                case "result":
                    self._respond_if_necessary(data)
                case other:
                    self.logger.debug("Ignoring unknown message type: %s", other)
        except Exception:
            self.logger.exception("Failed to dispatch message: %s", data)

    async def _dispatch_hass_event(self, data: "HassEventEnvelopeDict") -> None:
        """Dispatch a Home Assistant event to the event bus."""
        event = create_event_from_hass(data)
        await self.hassette.send_event(event.topic, event)

    async def _send_connection_lost_event(self) -> None:
        """Send a connection lost event to the event bus."""
        event = HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
        await self.hassette.send_event(event.topic, event)

    async def _send_connection_established_event(self) -> None:
        """Send a connection established event to the event bus."""
        event = HassetteSimpleEvent.create_event(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
        await self.hassette.send_event(event.topic, event)
