import asyncio
import json
import logging
import random
import time
import traceback
import typing
from contextlib import AsyncExitStack, suppress
from itertools import count
from typing import Any, ClassVar, cast

import aiohttp
import anyio
from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError, WSMsgType
from aiohttp.client_exceptions import ClientConnectionResetError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
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
    InvalidLifecycleTransitionError,
    RetryableConnectionClosedError,
)
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types import Topic
from hassette.types.enums import ConnectionState, RestartType
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.events.hass.raw import HassEventEnvelopeDict
    from hassette.resources.base import Resource


# Valid WebSocket connection state transitions.
# DISCONNECTED → CONNECTING: serve() begins first connection attempt
# CONNECTING → CONNECTED: handshake + auth + subscribe succeeded
# CONNECTING → DISCONNECTED: non-retryable failure or max retries exhausted
# CONNECTED → CONNECTING: connection lost, retrying (implies reconnect)
# CONNECTED → DISCONNECTED: clean shutdown
WS_VALID_TRANSITIONS: dict[ConnectionState, frozenset[ConnectionState]] = {
    ConnectionState.DISCONNECTED: frozenset({ConnectionState.CONNECTING}),
    ConnectionState.CONNECTING: frozenset({ConnectionState.CONNECTED, ConnectionState.DISCONNECTED}),
    ConnectionState.CONNECTED: frozenset({ConnectionState.CONNECTING, ConnectionState.DISCONNECTED}),
}

# classify errors once (easy to audit/change later)
NON_RETRYABLE = (InvalidAuthError, asyncio.CancelledError)
RETRYABLE = (
    RetryableConnectionClosedError,
    ServerDisconnectedError,
    ClientConnectorError,
    ClientOSError,
    CouldNotFindHomeAssistantError,
)
# Subset of RETRYABLE that qualifies for early-drop retry.
# Excludes ClientConnectorError and CouldNotFindHomeAssistantError — those indicate
# the server is unreachable, not that it dropped a post-auth connection.
EARLY_DROP_RETRYABLE = (RetryableConnectionClosedError, ServerDisconnectedError)
MAX_RETRY_ATTEMPTS = 5

# Number of stack frames to keep when logging an invalid connection-state transition.
# 3 is enough to show the caller that triggered the transition without dumping the
# full call stack down into asyncio internals.
INVALID_TRANSITION_TRACE_LIMIT = 3


class WebsocketService(Service):
    restart_spec: ClassVar[RestartSpec] = RestartSpec(
        restart_type=RestartType.TRANSIENT,
        budget_intensity=5,
        budget_period_seconds=300,
        startup_timeout_seconds=60,
    )

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

    _connected_at: float | None
    """Monotonic timestamp of the most recent successful connection, or None."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self.url = self.hassette.ws_url
        self._stack = AsyncExitStack()
        self._session = None
        self._ws = None
        self._response_futures = {}
        self._seq = count(1)
        self._recv_task = None
        self._subscription_ids = set()
        self._connect_lock = asyncio.Lock()
        self._connected_at = None
        self._connection_state: ConnectionState = ConnectionState.DISCONNECTED
        self._ever_connected: bool = False

    @property
    def config_log_level(self) -> LOG_LEVEL_TYPE:
        return self.hassette.config.logging.websocket

    @property
    def connection_state(self) -> ConnectionState:
        """Return the current WebSocket connection state (read-only)."""
        return self._connection_state

    @property
    def has_ever_connected(self) -> bool:
        """True once the connection has reached CONNECTED at least once; never reverts."""
        return self._ever_connected

    def set_connection_state(self, new: ConnectionState) -> None:
        """Transition to a new connection state with validation.

        Validates the transition against WS_VALID_TRANSITIONS. In strict lifecycle mode
        raises InvalidLifecycleTransitionError for invalid transitions; in non-strict
        (default) mode logs WARNING. Logs every valid transition at DEBUG with previous state.

        Args:
            new: The new connection state to transition to.

        Raises:
            InvalidLifecycleTransitionError: If the transition is invalid and strict_lifecycle is True.
        """
        old = self._connection_state
        if old == new:
            return

        if hasattr(self, "hassette"):
            allowed = WS_VALID_TRANSITIONS.get(old, frozenset())
            if new not in allowed:
                if getattr(self.hassette.config, "strict_lifecycle", False) is True:
                    raise InvalidLifecycleTransitionError(
                        from_status=old,
                        to_status=new,
                        resource_name=self.unique_name,
                    )
                frame_summary = "".join(traceback.format_stack(limit=INVALID_TRANSITION_TRACE_LIMIT)[:-1]).strip()
                self.logger.warning(
                    "Invalid WebSocket connection state transition for '%s': %r → %r\n%s",
                    self.unique_name,
                    old,
                    new,
                    frame_summary,
                )

        self.logger.debug("WebSocket: %s → %s", old, new)
        self._connection_state = new
        if new == ConnectionState.CONNECTED:
            self._ever_connected = True

    @property
    def resp_timeout_seconds(self) -> int:
        return self.hassette.config.websocket.response_timeout_seconds

    @property
    def connection_timeout_seconds(self) -> int:
        return self.hassette.config.websocket.connection_timeout_seconds

    @property
    def total_timeout_seconds(self) -> int:
        return self.hassette.config.websocket.total_timeout_seconds

    @property
    def heartbeat_interval_seconds(self) -> int:
        return self.hassette.config.websocket.heartbeat_interval_seconds

    @property
    def authentication_timeout_seconds(self) -> int:
        return self.hassette.config.websocket.authentication_timeout_seconds

    @property
    def cleanup_timeout_seconds(self) -> float:
        return self.hassette.config.websocket.cleanup_timeout_seconds

    @property
    def is_connected(self) -> bool:
        return self._connection_state == ConnectionState.CONNECTED

    def get_next_message_id(self) -> int:
        """Get the next message ID."""
        return next(self._seq)

    async def before_shutdown(self) -> None:
        await self.send_connection_lost_event()

    def log_resilience_budget(self) -> None:
        """Log the early-drop and connection retry budget that bounds recovery time."""
        config = self.hassette.config
        max_early_drops = config.websocket.early_drop_max_retries
        max_recovery = config.websocket.max_recovery_seconds
        self.logger.info(
            "WebSocket resilience budget: max ~%.0f minutes to permanent shutdown "
            "(early-drop: %d retries capped at %ds, connection: %d retries, service: %d restarts)",
            max_recovery / 60,
            max_early_drops,
            int(max_recovery),
            config.websocket.connect_retry_max_attempts,
            self.restart_spec.budget_intensity,
        )

    def compute_recovery_windows(self, recovery_started_at: float | None) -> tuple[float, float]:
        """Compute (seconds since last connect, seconds since recovery began) for drop classification."""
        elapsed = (time.monotonic() - self._connected_at) if self._connected_at is not None else float("inf")
        recovery_elapsed = (time.monotonic() - recovery_started_at) if recovery_started_at is not None else 0.0
        return elapsed, recovery_elapsed

    def is_early_drop(self, exc: Exception, early_drop_attempts: int, elapsed: float, recovery_elapsed: float) -> bool:
        """Classify exc as an early drop (retry in place) versus a genuine failure (propagate)."""
        config = self.hassette.config.websocket
        return (
            elapsed < config.early_drop_stable_window_seconds
            and isinstance(exc, EARLY_DROP_RETRYABLE)
            and early_drop_attempts < config.early_drop_max_retries
            and recovery_elapsed < config.max_recovery_seconds
        )

    async def handle_early_drop(
        self, exc: Exception, elapsed: float, early_drop_attempts: int, max_early_drops: int
    ) -> None:
        """Log, notify, clean up, and back off after an early connection drop, then set CONNECTING.

        Sends the connection-lost event before marking not-ready so the idempotency guard passes.
        """
        close_code = getattr(exc, "close_code", None)
        self.logger.warning(
            "WebSocket early drop detected (elapsed=%.1fs, attempt=%d/%d%s) — retrying",
            elapsed,
            early_drop_attempts,
            max_early_drops,
            f", close_code={close_code}" if close_code is not None else "",
        )
        await self.send_connection_lost_event()
        self.mark_not_ready(reason="Early drop detected")
        await self._emit_readiness_event()
        await self.partial_cleanup()
        await self.early_drop_backoff(early_drop_attempts)
        # Set CONNECTING before the next retry
        self.set_connection_state(ConnectionState.CONNECTING)

    async def handle_genuine_failure(self) -> None:
        """Transition to DISCONNECTED and notify listeners of a non-recoverable serve() failure."""
        self.set_connection_state(ConnectionState.DISCONNECTED)
        await self.send_connection_lost_event()
        self.mark_not_ready(reason="WebSocket recv loop failed")
        await self._emit_readiness_event()

    async def serve(self) -> None:
        """Connect to the WebSocket and run the receive loop."""
        self.log_resilience_budget()
        max_early_drops = self.hassette.config.websocket.early_drop_max_retries

        async with self._connect_lock:
            timeout = ClientTimeout(connect=self.connection_timeout_seconds, total=self.total_timeout_seconds)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                early_drop_attempts = 0
                recovery_started_at: float | None = None

                # Set CONNECTING before the first connection attempt
                self.set_connection_state(ConnectionState.CONNECTING)

                while True:
                    try:
                        self._recv_task = await self.make_connection(session)
                        await self._recv_task
                        return  # clean exit (shutdown)
                    except InvalidAuthError:
                        if early_drop_attempts > 0:
                            self.logger.error("Authentication failed on reconnect — possible token revocation")
                        self.set_connection_state(ConnectionState.DISCONNECTED)
                        raise
                    except Exception as exc:
                        elapsed, recovery_elapsed = self.compute_recovery_windows(recovery_started_at)
                        if self.is_early_drop(exc, early_drop_attempts, elapsed, recovery_elapsed):
                            if recovery_started_at is None:
                                recovery_started_at = time.monotonic()
                            early_drop_attempts += 1
                            await self.handle_early_drop(exc, elapsed, early_drop_attempts, max_early_drops)
                            continue
                        # Genuine failure — propagate to _serve_wrapper
                        await self.handle_genuine_failure()
                        raise

    async def connect_ws(self, session: aiohttp.ClientSession) -> None:
        """Open the WebSocket connection and authenticate.

        Sets self._ws. Converts ClientConnectorError with ConnectionRefusedError cause
        to CouldNotFindHomeAssistantError.

        Args:
            session: The aiohttp ClientSession to use for the WebSocket connection.
        """
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

    async def start_recv_and_subscribe(self) -> asyncio.Task:
        """Spawn the recv loop, send connection event, subscribe, mark ready, and record connected_at.

        Returns:
            The recv loop task.
        """
        # start reader first so send_and_wait can get replies; assign to self immediately
        # so partial_cleanup can cancel it if a later step (subscribe, event) raises
        recv_task = self.task_bucket.spawn(self.recv_loop(), name="ws:recv")
        self._recv_task = recv_task

        # CONNECTED before subscribe — send_json() gates on self.is_connected
        self.set_connection_state(ConnectionState.CONNECTED)

        await self.send_connection_established_event()
        self._subscription_ids.add(await self.subscribe_events())

        self.mark_ready(reason="WebSocket connected, authenticated, and subscribed")
        await self._emit_readiness_event()
        self._connected_at = time.monotonic()
        return recv_task

    async def partial_cleanup(self) -> None:
        """Cancel recv task, close WebSocket, clear futures and subscriptions.

        Does NOT close self._session — that is owned by serve()'s async with block.
        Suppresses all exceptions so cleanup never prevents retry.
        """
        if self._recv_task is not None:
            self._recv_task.cancel()
            with suppress(Exception):
                await asyncio.wait_for(
                    asyncio.gather(self._recv_task, return_exceptions=True),
                    timeout=self.cleanup_timeout_seconds,
                )

        if self._ws is not None and not self._ws.closed:
            with suppress(Exception):
                await self._ws.close()

        for fut in list(self._response_futures.values()):
            if not fut.done():
                with suppress(Exception):
                    fut.set_exception(RetryableConnectionClosedError("WebSocket disconnected"))
        self._response_futures.clear()
        self._subscription_ids.clear()
        self._ws = None
        self._recv_task = None

    async def early_drop_backoff(self, attempt: int) -> None:
        """Compute and sleep for an exponential-jitter backoff after an early drop.

        Args:
            attempt: The current attempt number (1-based).
        """
        config = self.hassette.config
        backoff = min(
            config.websocket.early_drop_backoff_initial_seconds * (2 ** (attempt - 1)),
            config.websocket.early_drop_backoff_max_seconds,
        ) + random.uniform(0, config.websocket.early_drop_backoff_initial_seconds)
        await asyncio.sleep(backoff)

    async def make_connection(self, session: aiohttp.ClientSession) -> asyncio.Task:
        self._connected_at = None

        # inner function so we can use `self` in the retry decorator
        @retry(
            retry=retry_if_not_exception_type(NON_RETRYABLE) | retry_if_exception_type(RETRYABLE),
            wait=wait_exponential_jitter(
                initial=self.hassette.config.websocket.connect_retry_initial_wait_seconds,
                max=self.hassette.config.websocket.connect_retry_max_wait_seconds,
            ),
            stop=stop_after_attempt(self.hassette.config.websocket.connect_retry_max_attempts),
            reraise=True,
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
        )
        async def _inner_connect() -> asyncio.Task:
            await self.partial_cleanup()
            await self.connect_ws(session)
            return await self.start_recv_and_subscribe()

        return await _inner_connect()

    async def recv_loop(self) -> None:
        while True:
            await self.raw_recv()

    async def send_and_await_response(self, payload: dict[str, Any], msg_id: int) -> Any:
        """Register a response future for msg_id, send payload, and await the reply.

        Registers the future before sending so a fast reply arriving before ``send_json``
        returns is never dropped. Always pops the future from ``_response_futures`` on
        exit — success, timeout, or any other exception.

        Args:
            payload: The JSON payload to send. Must already include ``"id": msg_id``.
            msg_id: The message id used to correlate the response future.

        Returns:
            The response payload once ``respond_if_necessary`` resolves the future.

        Raises:
            TimeoutError: If no response arrives within ``resp_timeout_seconds``.
        """
        fut = self.hassette.loop.create_future()
        self._response_futures[msg_id] = fut
        try:
            await self.send_json(**payload)
            return await asyncio.wait_for(fut, timeout=self.resp_timeout_seconds)
        finally:
            self._response_futures.pop(msg_id, None)

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

    async def cleanup(self) -> None:
        """Cleanup resources after the WebSocket connection is closed."""
        self.set_connection_state(ConnectionState.DISCONNECTED)

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

        # Close the aiohttp session. The sleep(0) yields to the event loop so
        # the underlying transport can finalize — without it, aiohttp's __del__
        # emits "Unclosed client session" during GC.
        if self._session:
            await self._session.close()
            await asyncio.sleep(0)
            self.logger.debug("Closed aiohttp session")

        await super().cleanup()

    async def send_and_wait(self, **data: Any) -> dict[str, Any]:
        """Send a message and wait for a response.

        Retries on transient failures (timeouts) with exponential backoff,
        matching the retry behavior of the REST API layer.

        Args:
            **data: The data to send as a JSON payload.

        Returns:
            The response data from the WebSocket.

        Raises:
            FailedMessageError: If sending the message fails after all retries.
        """
        caller_id = data.pop("id", None)

        @retry(
            retry=retry_if_exception(lambda e: isinstance(e, FailedMessageError) and e.code is None),
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
            wait=wait_exponential_jitter(),
            before_sleep=before_sleep_log(self.logger, logging.WARNING),
            reraise=True,
        )
        async def send_with_retry() -> dict[str, Any]:
            nonlocal caller_id
            if caller_id is not None:
                data["id"] = msg_id = caller_id
                caller_id = None
            else:
                data["id"] = msg_id = self.get_next_message_id()

            try:
                return await self.send_and_await_response(data, msg_id)
            except TimeoutError:
                raise FailedMessageError(
                    f"Response timed out after {self.resp_timeout_seconds}s (data: {data})"
                ) from None

        return await send_with_retry()

    def respond_if_necessary(self, message: dict) -> None:
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

    async def send_json(self, **data: Any) -> None:
        self.logger.debug("Sending WebSocket message: %s", data)

        if not self.is_connected:
            raise ConnectionClosedError("WebSocket connection is not established")

        # this should never be an issue because self.is_connected checks for this already
        assert self._ws is not None, "WebSocket must be initialized before sending messages"

        if "id" not in data:
            data["id"] = self.get_next_message_id()

        try:
            await self._ws.send_json(data)
        except ClientConnectionResetError:
            self.logger.error("WebSocket connection reset by peer")
            raise
        except Exception as exc:
            self.logger.exception("Exception when sending message: %s", data)
            raise FailedMessageError(f"Failed to send message: {data}") from exc

    async def authenticate(self) -> None:
        """Authenticate with the Home Assistant WebSocket API."""
        assert self._ws, "WebSocket must be initialized before authenticating"
        secret = self.hassette.config.token
        token = secret.get_secret_value() if secret is not None else None
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

    async def raw_recv(self) -> None:
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

            await self.dispatch(data)
            return

        if msg_type == WSMsgType.BINARY:
            self.logger.warning("Received binary message, which is not expected: %r", raw)
            return

        if msg_type in {WSMsgType.CLOSE, WSMsgType.CLOSED}:
            close_code = getattr(self._ws, "close_code", None)
            raise RetryableConnectionClosedError(f"WebSocket closed by peer ({msg_type!r})", close_code=close_code)

        # CLOSING arrives before CLOSED — exit early so the recv loop doesn't block on a half-closed socket
        if msg_type == WSMsgType.CLOSING:
            self.logger.debug("WebSocket is closing - exiting receive loop")
            close_code = getattr(self._ws, "close_code", None)
            raise RetryableConnectionClosedError("WebSocket is closing", close_code=close_code)

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
        except Exception:
            self.logger.exception("Failed to dispatch message: %s", data)

    async def dispatch_hass_event(self, data: "HassEventEnvelopeDict") -> None:
        """Dispatch a Home Assistant event to the event bus."""
        event = create_event_from_hass(data)
        await self.hassette.send_event(event)

    async def send_connection_lost_event(self) -> None:
        """Send a connection lost event to the event bus.

        Idempotent: skips if the service is already not-ready (prevents duplicate
        DISCONNECTED events during early-drop retry cycles and before_shutdown calls).
        Self-suppressing: bus dispatch errors are silently swallowed so callers never
        need external suppress() wrappers and a bus failure cannot mask a network error.
        """
        if not self.is_ready():
            return
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
        with suppress(Exception):
            await self.hassette.send_event(event)

    async def send_connection_established_event(self) -> None:
        """Send a connection established event to the event bus."""
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
        await self.hassette.send_event(event)
