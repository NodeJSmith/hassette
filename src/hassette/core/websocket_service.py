import asyncio
import json
import logging
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

from hassette.core.early_drop_policy import (
    compute_recovery_windows,
    early_drop_backoff,
    is_early_drop,
    log_resilience_budget,
)
from hassette.core.observer_list import ObserverList
from hassette.core.retry_policy import MAX_RETRY_ATTEMPTS
from hassette.events import HassetteSimpleEvent, RawStateChangeEvent, create_event_from_hass
from hassette.events.metadata import stamp_websocket_generation
from hassette.exceptions import (
    WS_NOT_CONNECTED_MESSAGE,
    ConnectionClosedError,
    CouldNotFindHomeAssistantError,
    FailedMessageError,
    InvalidAuthError,
    InvalidLifecycleTransitionError,
    RetryableConnectionClosedError,
)
from hassette.resources.lifecycle import mark_not_ready, mark_ready
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types import Topic
from hassette.types.enums import ConnectionState, RestartType
from hassette.types.types import LOG_LEVEL_TYPE

if typing.TYPE_CHECKING:
    from collections.abc import Callable

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
        degrade_on_confirmed_quiescent_refusal=False,
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

    _send_ready_event: asyncio.Event
    """Private send capability: auth succeeded and recv loop is running for request/reply setup."""

    _connected_at: float | None
    """Monotonic timestamp of the most recent successful connection, or None."""

    _connected_signal_active: bool
    """Whether the current external-readiness transition has emitted its public connected signal."""

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
        self._send_ready_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._first_connection_attempt_done_event = asyncio.Event()
        self._connected_at = None
        self._connected_signal_active = False
        self._connection_state: ConnectionState = ConnectionState.DISCONNECTED
        self._ever_connected: bool = False
        self._generation_seq = count(1)
        self._connected_generation: int | None = None
        self.connected_observers: ObserverList[Callable[[int], typing.Awaitable[None]]] = ObserverList(
            self.logger, "Connected"
        )
        self.disconnected_observers: ObserverList[Callable[[], typing.Awaitable[None]]] = ObserverList(
            self.logger, "Disconnected"
        )

    async def on_initialize(self) -> None:
        """Mark the service lifecycle-ready unconditionally, independent of HA reachability.

        This separates "service lifecycle ready" (the service is running and will attempt
        connections) from "HA connected" (the WebSocket handshake succeeded). Without this,
        WebsocketService's wave in run_forever() times out when HA is unreachable, triggering
        a fatal shutdown before later waves (e.g. WebApiService) ever start. serve() begins
        the actual connection loop afterward.
        """
        mark_ready(self, reason="WebSocket service initialized")

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
        else:
            if hasattr(self, "_connected_event"):
                self._connected_event.clear()
            if hasattr(self, "_connected_generation"):
                self._connected_generation = None

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

    async def wait_connected(self, *, timeout: float | None = None) -> bool:
        """Wait until the Home Assistant WebSocket is connected and subscribed.

        Resource readiness only means this service is running and attempting to connect;
        callers that need HA data should wait on the connection state explicitly.
        """
        if self.is_connected and self._connected_event.is_set():
            return True
        try:
            await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)
        except TimeoutError:
            return False
        return self.is_connected

    def get_connected_generation(self) -> int | None:
        """Return the active externally ready connection generation, if any."""
        if not self.is_connected or not self._connected_event.is_set():
            return None
        return self._connected_generation

    async def wait_connected_generation(self, *, timeout: float | None = None) -> int | None:
        """Wait for an externally ready connection and return its active generation."""
        if self.get_connected_generation() is not None and self._connected_event.is_set():
            return self._connected_generation
        connected = await self.wait_connected(timeout=timeout)
        if not connected:
            return None
        return self._connected_generation

    async def wait_initial_connection(self, *, timeout: float | None = None) -> bool:
        """Wait for initial connection success, or the first failed connection attempt.

        This lets startup state sync avoid racing ahead of the WebSocket connection attempt
        without blocking optional-HA startup until the full retry budget is exhausted.
        """
        if self.is_connected and self._connected_event.is_set():
            return True
        if self._first_connection_attempt_done_event.is_set():
            return False

        connected_task = asyncio.create_task(self._connected_event.wait())
        attempt_done_task = asyncio.create_task(self._first_connection_attempt_done_event.wait())
        try:
            done, _pending = await asyncio.wait(
                {connected_task, attempt_done_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in (connected_task, attempt_done_task):
                if not task.done():
                    task.cancel()

        if not done:
            return False
        return self.is_connected and self._connected_event.is_set()

    def get_next_message_id(self) -> int:
        """Get the next message ID."""
        return next(self._seq)

    async def before_shutdown(self) -> None:
        await self._notify_disconnected_observers()
        await self.send_connection_lost_event()

    async def _notify_disconnected_observers(self) -> None:
        if not self._connected_signal_active:
            return
        await self.disconnected_observers.notify()

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
        self.set_connection_state(ConnectionState.CONNECTING)
        self._send_ready_event.clear()
        await self._notify_disconnected_observers()
        await self.send_connection_lost_event()
        mark_not_ready(self, reason="Early drop detected")
        await self._emit_readiness_event()
        await self.partial_cleanup()
        await early_drop_backoff(self.hassette.config.websocket, early_drop_attempts)

    async def handle_genuine_failure(self) -> None:
        """Transition to DISCONNECTED and notify listeners of a non-recoverable serve() failure."""
        self.set_connection_state(ConnectionState.DISCONNECTED)
        self._send_ready_event.clear()
        await self._notify_disconnected_observers()
        await self.send_connection_lost_event()
        mark_not_ready(self, reason="WebSocket recv loop failed")
        await self._emit_readiness_event()

    async def serve(self) -> None:
        """Connect to the WebSocket and run the receive loop."""
        log_resilience_budget(self.hassette.config.websocket, self.logger, self.restart_spec.budget_intensity)
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
                        elapsed, recovery_elapsed = compute_recovery_windows(self._connected_at, recovery_started_at)
                        if is_early_drop(
                            self.hassette.config.websocket, exc, early_drop_attempts, elapsed, recovery_elapsed
                        ):
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
        """Spawn the recv loop, open private send capability, subscribe, then advertise readiness.

        Returns:
            The recv loop task.
        """
        # start reader first so send_and_wait can get replies; assign to self immediately
        # so partial_cleanup can cancel it if a later step (subscribe, event) raises
        recv_task = self.task_bucket.spawn(self.recv_loop(), name="ws:recv")
        self._recv_task = recv_task
        recv_task.add_done_callback(self._handle_recv_task_done)

        self._send_ready_event.set()
        self._subscription_ids.add(await self.subscribe_events())
        self._connected_generation = next(self._generation_seq)
        self.set_connection_state(ConnectionState.CONNECTED)

        self._connected_event.set()
        self._first_connection_attempt_done_event.set()

        self._connected_at = time.monotonic()

        mark_ready(self, reason="WebSocket connected, authenticated, and subscribed")
        await self._emit_readiness_event()
        self._connected_signal_active = True
        await self.connected_observers.notify(self._connected_generation)
        with suppress(Exception):
            await self.send_connection_established_event()
        return recv_task

    def _handle_recv_task_done(self, task: asyncio.Task) -> None:
        """Invalidate connection state the instant the recv task dies, independent of serve().

        serve() only learns a recv task died once it gets the task handle back from
        start_recv_and_subscribe() and awaits it — but that method can be delayed arbitrarily
        long by connected_observers.notify() running a slow observer (e.g. StateProxy's initial
        sync). Attaching this callback directly to the task (asyncio.Task.add_done_callback
        fires synchronously in the event loop the moment the task completes, regardless of who
        is awaiting it) means get_connected_generation()/is_connected reflect the disconnect the
        instant the task actually dies, not only after the whole notification pass completes.

        Deliberate cancellation (serve()'s own cleanup tearing the task down on purpose) is not a
        failure and is skipped here — those paths already run their own state transitions.
        set_connection_state() itself no-ops if the state is already DISCONNECTED, so this never
        duplicates or conflicts with serve()'s subsequent handle_early_drop/handle_genuine_failure
        cleanup — it only makes the transition visible earlier.
        """
        if task is not self._recv_task:
            return
        if task.cancelled():
            return
        if task.exception() is None:
            return
        self.set_connection_state(ConnectionState.DISCONNECTED)

    async def partial_cleanup(self) -> None:
        """Cancel recv task, close WebSocket, clear futures and subscriptions.

        Does NOT close self._session — that is owned by serve()'s async with block.
        Suppresses all exceptions so cleanup never prevents retry.
        """
        self._send_ready_event.clear()

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
            try:
                await self.connect_ws(session)
                return await self.start_recv_and_subscribe()
            except Exception:
                self._first_connection_attempt_done_event.set()
                raise

        return await _inner_connect()

    async def recv_loop(self) -> None:
        while True:
            await self.raw_recv()

    async def send_and_await_response(
        self, payload: dict[str, Any], msg_id: int, *, allow_pre_ready: bool = False
    ) -> Any:
        """Register a response future for msg_id, send payload, and await the reply.

        Registers the future before sending so a fast reply arriving before ``send_json``
        returns is never dropped. Always pops the future from ``_response_futures`` on
        exit — success, timeout, or any other exception.

        Args:
            payload: The JSON payload to send. Must already include ``"id": msg_id``.
            msg_id: The message id used to correlate the response future.
            allow_pre_ready: Whether to use the private pre-readiness send path for setup traffic.

        Returns:
            The response payload once ``respond_if_necessary`` resolves the future.

        Raises:
            TimeoutError: If no response arrives within ``resp_timeout_seconds``.
        """
        fut = self.hassette.loop.create_future()
        self._response_futures[msg_id] = fut
        try:
            if allow_pre_ready:
                await self._send_json_when_socket_live(**payload)
            else:
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
                    await self._send_json_when_socket_live(
                        type="unsubscribe_events",
                        subscription=last_abandoned_id,
                        id=self.get_next_message_id(),
                    )

            msg_id = self.get_next_message_id()
            try:
                await self.send_and_await_response({**payload, "id": msg_id}, msg_id, allow_pre_ready=True)
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

        # Try to unsubscribe (best-effort; ignore errors if socket is going away). This must run
        # before the send-ready gate closes below — send_json() raises immediately once the gate
        # is shut, which would otherwise make this loop a silent no-op.
        if self._ws and not self._ws.closed and self._subscription_ids:
            for sid in list(self._subscription_ids):
                with suppress(Exception):
                    await self.send_json(type="unsubscribe_events", subscription=sid)
            self._subscription_ids.clear()

        self._send_ready_event.clear()

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

    async def _send_json_when_socket_live(self, **data: Any) -> None:
        self.logger.debug("Sending WebSocket message: %s", data)

        if not self._send_ready_event.is_set():
            raise ConnectionClosedError(WS_NOT_CONNECTED_MESSAGE)

        # The private send gate is only opened after authentication assigns the socket.
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

    async def send_json(self, **data: Any) -> None:
        await self._send_json_when_socket_live(**data)

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
            raise RuntimeError(WS_NOT_CONNECTED_MESSAGE)

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
        if isinstance(event, RawStateChangeEvent):
            stamp_websocket_generation(event, self.get_connected_generation())
        await self.hassette.send_event(event)

    async def send_connection_lost_event(self) -> None:
        """Send a connection lost event to the event bus.

        Idempotent: skips if the connection has never been established (prevents spurious
        DISCONNECTED events before the first successful connection, and duplicate events
        during early-drop retry cycles, failed pre-readiness reconnect attempts, and
        before_shutdown calls). Gated on the active public connected signal rather than
        `is_ready()` because `mark_ready()` now fires unconditionally in `on_initialize()` —
        readiness no longer implies a connection was ever established.
        Self-suppressing: bus dispatch errors are silently swallowed so callers never
        need external suppress() wrappers and a bus failure cannot mask a network error.
        """
        if not self._connected_signal_active:
            return
        self._connected_signal_active = False
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
        with suppress(Exception):
            await self.hassette.send_event(event)

    async def send_connection_established_event(self) -> None:
        """Send a connection established event to the event bus."""
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
        await self.hassette.send_event(event)
