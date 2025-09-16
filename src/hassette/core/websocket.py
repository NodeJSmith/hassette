import asyncio
import json
import logging
import typing
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from itertools import count
from logging import getLogger
from typing import Any, cast

import aiohttp
import anyio
import tenacity
from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    retry_if_not_exception_type,
)

from hassette.core.classes import Service
from hassette.core.enums import ResourceStatus
from hassette.core.events import HassEventEnvelopeDict, create_event_from_hass, create_websocket_status_event
from hassette.exceptions import (
    ConnectionClosedError,
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    RetryableConnectionClosedError,
)

if typing.TYPE_CHECKING:
    from hassette.core.core import Hassette

LOGGER = getLogger(__name__)


@dataclass(frozen=True, eq=True)
class FailedMessagePayload:
    id: int
    error: str


class _Websocket(Service):
    def __init__(self, hassette: "Hassette"):
        super().__init__(hassette)
        self.hassette = hassette
        self.url = self.hassette.config.ws_url
        self._stack = AsyncExitStack()
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._response_futures: dict[int, asyncio.Future[Any]] = {}
        self._seq = count(1)

        self._recv_task: asyncio.Task | None = None
        self._subscription_ids: set[int] = set()
        self._connect_lock = asyncio.Lock()  # if you don't already have it

    @property
    def timeout_seconds(self) -> int:
        return self.hassette.config.websocket_timeout_seconds

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

    async def run_forever(self) -> None:
        async with self._connect_lock:
            try:
                await self._connect_and_run()
            except (RetryableConnectionClosedError, ServerDisconnectedError, ClientConnectorError, ClientOSError) as e:
                await self._send_connection_lost_event(f"{type(e).__name__}: {e}")
                await self.handle_failed(e)
            except asyncio.CancelledError:
                await self._send_connection_lost_event("Connection cancelled")
                await self.handle_stop()
            except Exception as e:
                await self.handle_crash(e)
                raise
            finally:
                await self._cleanup()

    async def _connect_and_run(self) -> None:
        """Connect to the WebSocket and run the receive loop."""

        # we wait_fixed for 1 second and try 60 times
        # this lets us (hopefully) get subscribed ASAP after HA is back up
        # instead of waiting exponential and potentially being seconds behind

        # the reason we want to be ASAP is so we can use events like homeassistant_start(ed) to
        # adjust behavior in things like the Api class

        timeout = ClientTimeout(connect=5, total=30)
        async for attempt in AsyncRetrying(
            retry=retry_if_not_exception_type(
                (InvalidAuthError, asyncio.CancelledError, CouldNotFindHomeAssistantError)
            )
            | retry_if_exception_type(
                (RetryableConnectionClosedError, ServerDisconnectedError, ClientConnectorError, ClientOSError)
            ),
            wait=tenacity.wait_fixed(1),
            stop=tenacity.stop_after_attempt(60),
            reraise=True,
            before_sleep=before_sleep_log(LOGGER, logging.WARNING),
        ):
            with attempt:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    self._session = session
                    try:
                        self._ws = await session.ws_connect(self.url, heartbeat=30)
                    except ClientConnectorError as exc:
                        if exc.__cause__ and isinstance(exc.__cause__, ConnectionRefusedError):
                            raise CouldNotFindHomeAssistantError(self.url) from exc.__cause__
                        raise

                    self.logger.debug("Connected to WebSocket at %s", self.url)
                    await self.authenticate()

                    # start the reader first so send_and_wait can get replies
                    self._recv_task = self.hassette.create_task(self._recv_loop())

                    sub_all_id = await self._subscribe_events()  # uses send_and_wait internally
                    self._subscription_ids.add(sub_all_id)

                    await self.handle_start()
                    event = create_websocket_status_event(connected=True, url=self.url)
                    await self.hassette.send_event(event.topic, event)

                    # Keep running until recv loop ends (disconnect, error, etc.)
                    await self._recv_task

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

    async def handle_start(self) -> None:
        """Handle a start event for the service."""

        if self.status != ResourceStatus.RUNNING:
            await super().handle_start()

    async def _cleanup(self) -> None:
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

    async def send_and_wait(self, **data: Any) -> dict[str, Any]:
        """Send a message and wait for a response.

        Args:
            **data: The data to send as a JSON payload.

        Returns:
            dict[str, Any]: The response data from the WebSocket.

        Raises:
            FailedMessageError: If sending the message fails or times out.
        """
        if "id" not in data:
            data["id"] = msg_id = self.get_next_message_id()
        else:
            msg_id = data["id"]

        fut = asyncio.get_running_loop().create_future()
        self._response_futures[msg_id] = fut
        try:
            await self.send_json(**data)
            return await asyncio.wait_for(fut, timeout=self.timeout_seconds)
        except TimeoutError:
            raise FailedMessageError(f"Response timed out after {self.timeout_seconds}s (data: {data})") from None
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
        token = self.hassette.config.token.get_secret_value()
        truncated_token = self.hassette.config.truncated_token
        ws_url = self.hassette.config.ws_url

        with anyio.fail_after(10):
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
                raise InvalidAuthError(f"Authentication failed - invalid access token ({truncated_token})")

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

    async def _dispatch_hass_event(self, data: HassEventEnvelopeDict) -> None:
        """Dispatch a Home Assistant event to the event bus."""
        event = create_event_from_hass(data)
        await self.hassette.send_event(event.topic, event)

    async def _send_connection_lost_event(self, error: str) -> None:
        """Send a connection lost event to the event bus."""
        event = create_websocket_status_event(connected=False, error=error)
        await self.hassette.send_event(event.topic, event)
