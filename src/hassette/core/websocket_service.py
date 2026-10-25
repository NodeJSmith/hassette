import asyncio
import time
import traceback
import typing
from contextlib import AsyncExitStack, suppress
from itertools import count
from typing import ClassVar

import aiohttp
import anyio
from aiohttp import ClientTimeout
from hassette_wire import LogLevel

from hassette.core.observer_list import ObserverList
from hassette.core.websocket_io import WebsocketMessageIOMixin
from hassette.core.websocket_reconnect import (
    AUTH_REJECTED_REASON,
    CONNECTED_REASON,
    CORE_NOT_RUNNING_REASON,
    CORE_RUNNING_RECHECK_SECONDS,
    CORE_STATE_RUNNING,
    CORE_STATES_SHUTTING_DOWN,
    NOT_CONNECTED_REASON,
    PROPAGATED_EXCEPTIONS,
    WS_MAX_MSG_SIZE,
    CoreShuttingDownError,
    Disposition,
    OutageLog,
    ReconnectPolicy,
    RetryPlan,
    event_set_within,
    race_recv_task,
    raise_recv_task_end,
)
from hassette.core.websocket_responses import PendingResponses
from hassette.events import HassetteSimpleEvent, create_event_from_hass
from hassette.exceptions import InvalidAuthError, InvalidLifecycleTransitionError
from hassette.resources.lifecycle import mark_ready, set_ready_reason
from hassette.resources.restart import RestartSpec
from hassette.resources.service import Service
from hassette.types import Topic
from hassette.types.enums import ConnectionState, RestartType
from hassette.utils.service_utils import cancel_and_drain

if typing.TYPE_CHECKING:
    from collections.abc import Callable

    from hassette import Hassette
    from hassette.events.hass.raw import HassEventEnvelopeDict
    from hassette.resources.base import Resource


AUTHENTICATION_TIMEOUT_SECONDS = 10
"""Seconds to wait for Home Assistant to answer the auth handshake."""

TOTAL_TIMEOUT_SECONDS = 30
"""Total seconds aiohttp allows for one WebSocket operation (``ClientTimeout.total``)."""

CLEANUP_TIMEOUT_SECONDS = 2.0
"""Seconds to wait for the receive task to finish cancelling during partial cleanup."""


# Valid WebSocket connection state transitions. Failed attempts and their backoffs stay in
# CONNECTING with no transition, so an outage produces no per-attempt state changes.
# DISCONNECTED → CONNECTING: serve() starts an attempt (first, or after the recv task died)
# CONNECTING → CONNECTED: Home Assistant's core state reached RUNNING
# CONNECTING → AUTH_FAILED: the token was rejected and serve() parked
# CONNECTING → DISCONNECTED: the recv task died during the RUNNING wait, or shutdown
# CONNECTED → CONNECTING: serve() handles the drop of an established connection
# CONNECTED → DISCONNECTED: the recv task died, or shutdown
# AUTH_FAILED → DISCONNECTED: shutdown (leaving AUTH_FAILED otherwise takes a process restart)
WS_VALID_TRANSITIONS: dict[ConnectionState, frozenset[ConnectionState]] = {
    ConnectionState.DISCONNECTED: frozenset({ConnectionState.CONNECTING}),
    ConnectionState.CONNECTING: frozenset(
        {ConnectionState.CONNECTED, ConnectionState.AUTH_FAILED, ConnectionState.DISCONNECTED}
    ),
    ConnectionState.CONNECTED: frozenset({ConnectionState.CONNECTING, ConnectionState.DISCONNECTED}),
    ConnectionState.AUTH_FAILED: frozenset({ConnectionState.DISCONNECTED}),
}

# Number of stack frames to keep when logging an invalid connection-state transition.
# 3 is enough to show the caller that triggered the transition without dumping the
# full call stack down into asyncio internals.
INVALID_TRANSITION_TRACE_LIMIT = 3


class WebsocketService(WebsocketMessageIOMixin, Service):
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

    _pending: PendingResponses
    """Owns response-future correlation and timed-out-write tracking for this connection."""

    _recv_task: asyncio.Task | None
    """Task for receiving messages from the WebSocket."""

    _subscription_ids: set[int]
    """Set of active subscription IDs."""

    _connect_lock: asyncio.Lock
    """Lock to prevent concurrent connection attempts."""

    _send_ready_event: asyncio.Event
    """Send gate: auth succeeded and the recv loop is running.

    This is the only send gate the service enforces. It opens before the event subscription
    confirms so setup traffic (``subscribe_events``) can flow, which means it does not imply
    external readiness: callers that must not send before CONNECTED (e.g. ``Api``) check
    ``is_connected`` themselves.
    """

    _connected_at: float | None
    """Monotonic timestamp of the most recent successful connection, or None."""

    _observers_announced: bool
    """Whether the connected observers were notified for this connection, so the disconnected ones are owed."""

    _bus_announced: bool
    """Whether ``websocket_connected`` reached the bus for this connection, so ``websocket_disconnected`` is owed."""

    _held_started_event: "HassEventEnvelopeDict | None"
    """``homeassistant_started`` caught by the RUNNING gate, dispatched once the connection is CONNECTED (D12)."""

    def __init__(self, hassette: "Hassette", *, parent: "Resource | None" = None) -> None:
        super().__init__(hassette, parent=parent)
        self.url = self.hassette.ws_url
        self._stack = AsyncExitStack()
        self._session = None
        self._ws = None
        self._pending = PendingResponses(self.logger)
        self._seq = count(1)
        self._recv_task = None
        self._subscription_ids = set()
        self._connect_lock = asyncio.Lock()
        self._send_ready_event = asyncio.Event()
        self._connected_event = asyncio.Event()
        self._core_started_event = asyncio.Event()
        self._policy = ReconnectPolicy()
        self._outage_log = OutageLog(self.logger, self.url)
        self._connected_at = None
        self._observers_announced = False
        self._bus_announced = False
        self._held_started_event = None
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
        the actual connection loop afterward. Readiness then stays set until shutdown; the HA
        connection's status is shown through the ready reason (``report_connection_status``).

        Both resolved Home Assistant URLs are logged here, before any connection attempt, so a
        ``base_url`` whose path is wrong shows up in the log even when every connection fails.
        """
        self.logger.info("Home Assistant URLs: REST %s, WebSocket %s", self.hassette.rest_url, self.hassette.ws_url)
        mark_ready(self, reason="WebSocket service initialized")

    @property
    def config_log_level(self) -> LogLevel:
        """Return the ``logging.websocket`` level from the config."""
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

        Only the first CONNECTED is logged at INFO here, so the Home Assistant connection is
        visible at the default log level. That is the line the quickstart tells a new user to
        look for to confirm their URL and token work. Reconnects and drops are logged by
        ``OutageLog``.

        Args:
            new: The new connection state to transition to.

        Raises:
            InvalidLifecycleTransitionError: If the transition is invalid and strict_lifecycle is True.
        """
        old = self._connection_state
        if old == new:
            return

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
            # A reconnect is logged by OutageLog.record_connected, with the outage's duration.
            if not self._ever_connected:
                self.logger.info("Connected to Home Assistant at %s", self.url)
            self._ever_connected = True
        else:
            # Leaving CONNECTED is logged by OutageLog.record_failure, which knows whether it was a flap.
            self._connected_event.clear()
            self._connected_generation = None

    @property
    def connection_timeout_seconds(self) -> int:
        """Seconds aiohttp allows to open the WebSocket connection, from the websocket config."""
        return self.hassette.config.websocket.connection_timeout_seconds

    @property
    def heartbeat_interval_seconds(self) -> int:
        """Seconds between aiohttp keep-alive pings on the WebSocket, from the websocket config."""
        return self.hassette.config.websocket.heartbeat_interval_seconds

    @property
    def is_connected(self) -> bool:
        """True while the connection state is CONNECTED, i.e. externally ready for HA traffic."""
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

    async def before_shutdown(self) -> None:
        """Notify disconnect observers and send the connection-lost event before teardown begins."""
        await self._notify_disconnected_observers()
        await self.send_connection_lost_event()

    async def _notify_disconnected_observers(self) -> None:
        if not self._observers_announced:
            return
        self._observers_announced = False
        await self.disconnected_observers.notify()

    async def serve(self) -> None:
        """Connect to Home Assistant and keep reconnecting in place until shutdown.

        This is the connection's only retry loop: no Home Assistant-side failure leaves it, so an
        HA restart or outage never reaches ServiceWatcher. ``ReconnectPolicy`` classifies each
        failure and paces the next attempt; a rejected token parks the loop instead. Only the
        exceptions in ``PROPAGATED_EXCEPTIONS`` (and cancellation, at shutdown) escape.
        """
        async with self._connect_lock:
            timeout = ClientTimeout(connect=self.connection_timeout_seconds, total=TOTAL_TIMEOUT_SECONDS)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                self._policy = ReconnectPolicy()
                self._outage_log = OutageLog(self.logger, self.url)
                self.set_connection_state(ConnectionState.CONNECTING)

                while True:
                    try:
                        await self.run_connection(session)
                        return  # run_connection always raises; only a test stub returns
                    except PROPAGATED_EXCEPTIONS:
                        raise
                    except Exception as exc:
                        plan = await self.handle_connection_failure(exc)

                    if plan.delay is None:  # Disposition.PARK, the only plan without a delay
                        await self.park()
                        return  # unreachable: park() only ends by cancellation at shutdown
                    await asyncio.sleep(plan.delay)

    async def run_connection(self, session: aiohttp.ClientSession) -> None:
        """Run one connection from handshake to drop; always raises whatever ended it."""
        await self.connect_ws(session)
        recv_task = await self.start_recv_and_subscribe()
        await self.wait_for_core_running(recv_task)
        await self.mark_connected(recv_task)
        # asyncio.wait rather than awaiting the task: a recv task cancelled by anything but our own
        # cleanup is a lost connection, not a shutdown of serve().
        await asyncio.wait({recv_task})
        raise_recv_task_end(recv_task)

    async def handle_connection_failure(self, exc: Exception) -> RetryPlan:
        """Tear down the failed connection, notify listeners once, and decide the next step.

        Each disconnected signal fires only if its connected counterpart did (``_observers_announced``,
        ``_bus_announced``).
        """
        now = time.monotonic()
        connected_for = (now - self._connected_at) if self._connected_at is not None else None
        self._connected_at = None

        self._send_ready_event.clear()
        self._policy.on_connection_ended(connected_for)
        plan = self._policy.on_failure(exc)
        if plan.disposition is not Disposition.PARK:
            self.set_connection_state(ConnectionState.CONNECTING)

        await self._notify_disconnected_observers()
        await self.send_connection_lost_event()
        if plan.disposition is not Disposition.PARK:  # park() reports its own reason
            await self.report_connection_status(NOT_CONNECTED_REASON)
        await self.partial_cleanup()

        self._outage_log.record_failure(
            exc, plan, now=now, connected_for=connected_for, has_ever_connected=self.has_ever_connected
        )
        return plan

    async def park(self) -> None:
        """Stay up without reconnecting until shutdown cancels serve() (D3, D10)."""
        self.set_connection_state(ConnectionState.AUTH_FAILED)
        await self.report_connection_status(AUTH_REJECTED_REASON)
        await asyncio.Event().wait()  # never set: cancellation at shutdown is the only exit

    async def report_connection_status(self, reason: str) -> None:
        """Show the HA connection's status as this service's ready reason (D10).

        Lifecycle readiness is untouched: it stays set from ``on_initialize`` to shutdown, so the
        connection never gates a startup wave. A status event is emitted only when the reason
        changes, so retries with an unchanged cause emit nothing (D11). Shutdown's reason wins.
        """
        if self.shutdown_event.is_set() or reason == self._ready_reason:
            return
        set_ready_reason(self, reason)
        await self._emit_readiness_event()

    async def connect_ws(self, session: aiohttp.ClientSession) -> None:
        """Open the WebSocket connection and authenticate.

        Sets self._ws. Messages larger than ``WS_MAX_MSG_SIZE`` close the socket with code 1009.

        Args:
            session: The aiohttp ClientSession to use for the WebSocket connection.
        """
        self._session = session
        self._ws = await session.ws_connect(
            self.url,
            heartbeat=self.heartbeat_interval_seconds,
            ssl=self.hassette.config.verify_ssl,
            max_msg_size=WS_MAX_MSG_SIZE,
        )
        self.logger.debug("Connected to WebSocket at %s", self.url)
        await self.authenticate()

    async def start_recv_and_subscribe(self) -> asyncio.Task:
        """Spawn the recv loop, open the send gate, and subscribe to Home Assistant events.

        Returns:
            The recv loop task.
        """
        self._held_started_event = None  # one held over from a failed attempt belongs to that attempt
        # start reader first so send_and_wait can get replies; assign to self immediately
        # so partial_cleanup can cancel it if a later step (subscribe, event) raises
        recv_task = self.task_bucket.spawn(self.recv_loop(), name="ws:recv")
        self._recv_task = recv_task
        recv_task.add_done_callback(self._handle_recv_task_done)

        self._send_ready_event.set()
        self._subscription_ids.add(await self.subscribe_events())
        return recv_task

    async def wait_for_core_running(self, recv_task: asyncio.Task) -> None:
        """Hold the connection in CONNECTING until Home Assistant's core state is RUNNING (D12).

        Reads ``get_config`` over the auth-level send gate (``Api.get_config`` refuses anything
        short of CONNECTED). While HA is starting, waits for ``homeassistant_started`` (caught by
        ``dispatch_hass_event``) and re-reads ``get_config`` every ``CORE_RUNNING_RECHECK_SECONDS``
        in case that event was missed. There is no deadline: HA bounds STARTING itself.

        Raises:
            CoreShuttingDownError: If HA reports a shutting-down core state.
        """
        while True:
            self._core_started_event.clear()
            config = await race_recv_task(self.send_and_wait(type="get_config"), recv_task)
            core_state = str(config["state"])
            if core_state == CORE_STATE_RUNNING:
                return
            if core_state in CORE_STATES_SHUTTING_DOWN:
                raise CoreShuttingDownError(core_state)

            await self.report_connection_status(CORE_NOT_RUNNING_REASON.format(core_state))
            self._outage_log.record_core_wait(
                core_state, now=time.monotonic(), has_ever_connected=self.has_ever_connected
            )
            # homeassistant_started means RUNNING, so it ends the wait without another get_config.
            if await race_recv_task(
                event_set_within(self._core_started_event, CORE_RUNNING_RECHECK_SECONDS), recv_task
            ):
                return

    async def mark_connected(self, recv_task: asyncio.Task) -> None:
        """Advertise external readiness: CONNECTED, a new generation, observers, and the public event."""
        # The recv task can die between the gate's last reply and this call; never advertise a dead socket.
        if recv_task.done():
            raise_recv_task_end(recv_task)

        was_ever_connected = self.has_ever_connected  # read before set_connection_state latches it
        generation = next(self._generation_seq)
        self._connected_generation = generation
        self.set_connection_state(ConnectionState.CONNECTED)
        self._connected_event.set()
        self._connected_at = time.monotonic()
        self._policy.on_connected()
        self._outage_log.record_connected(now=self._connected_at, was_ever_connected=was_ever_connected)

        await self.report_connection_status(CONNECTED_REASON)
        if recv_task.done():  # died during the await: don't announce it to observers or apps
            raise_recv_task_end(recv_task)
        self._observers_announced = True
        await self.connected_observers.notify(generation)
        started, self._held_started_event = self._held_started_event, None
        try:
            await self.send_connection_established_event()
            if started is not None:
                await self.hassette.send_event(create_event_from_hass(started))
        except Exception:
            self.logger.exception("Failed to send the connection events to the bus")

    def _handle_recv_task_done(self, task: asyncio.Task) -> None:
        """Invalidate connection state and fail pending replies the instant the recv task dies.

        serve() only notices the death once it awaits the task again, which a slow connected
        observer (StateProxy's initial sync) can delay. A done-callback fires immediately, so
        is_connected and pending callers see the drop now. Our own cleanup detaches the task
        before cancelling it, so any task still attached ended because the connection did,
        cancellation by anything else included.
        """
        if task is not self._recv_task:
            return
        self._pending.fail_all(self._ws.close_code if self._ws is not None else None)
        self.set_connection_state(ConnectionState.DISCONNECTED)

    async def partial_cleanup(self) -> None:
        """Cancel recv task, close WebSocket, clear futures and subscriptions.

        Does NOT close self._session — that is owned by serve()'s async with block.
        Suppresses all exceptions so cleanup never prevents retry.
        """
        # The code from a peer CLOSE frame or a detected abnormal closure (1006, e.g. heartbeat
        # timeout). Read before close() below, which would stamp hassette's own code on an open socket.
        close_code = self._ws.close_code if self._ws is not None else None
        self._send_ready_event.clear()

        if (recv_task := self._recv_task) is not None:
            self._recv_task = None  # detach first: the done-callback ignores a task we cancel
            recv_task.cancel()
            # asyncio.timeout, not wait_for: on 3.11 wait_for swallows a cancellation that lands
            # as its inner awaitable completes, so shutdown would resume the reconnect loop.
            with suppress(Exception):
                async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
                    await asyncio.gather(recv_task, return_exceptions=True)

        if self._ws is not None and not self._ws.closed:
            with suppress(Exception):
                await self._ws.close()

        self._pending.fail_all(close_code)
        self._subscription_ids.clear()
        self._ws = None

    async def cleanup(self) -> None:
        """Cleanup resources after the WebSocket connection is closed."""
        self.set_connection_state(ConnectionState.DISCONNECTED)

        # Set exceptions for all pending response futures, before the close() below can replace
        # the socket's close code (peer CLOSE frame or detected abnormal closure) with our own.
        self._pending.fail_all(self._ws.close_code if self._ws is not None else None)

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
        if (recv_task := self._recv_task) is not None:
            self._recv_task = None  # detach first: the done-callback ignores a task we cancel
            await cancel_and_drain(recv_task)

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

    async def authenticate(self) -> None:
        """Authenticate with the Home Assistant WebSocket API."""
        if not self._ws:
            raise RuntimeError("WebSocket must be initialized before authenticating")
        secret = self.hassette.config.token
        token = secret.get_secret_value() if secret is not None else None
        truncated_token = self.hassette.config.truncated_token
        ws_url = self.hassette.ws_url

        with anyio.fail_after(AUTHENTICATION_TIMEOUT_SECONDS):
            msg = await self._ws.receive_json()
            if msg["type"] != "auth_required":
                raise RuntimeError(f"Unexpected authentication response: {msg}")
            await self._ws.send_json({"type": "auth", "access_token": token})
            msg = await self._ws.receive_json()

            # happy path
            if msg["type"] == "auth_ok":
                self.logger.debug("Authenticated successfully with Home Assistant at %s", ws_url)
                return

            # serve()'s OutageLog reports the rejection at the level D3's retry-or-park decision calls for.
            if msg["type"] == "auth_invalid":
                raise InvalidAuthError(f"Authentication failed - invalid access token ({truncated_token}) for {ws_url}")

            raise RuntimeError(f"Unexpected authentication response: {msg}")

    async def send_connection_lost_event(self) -> None:
        """Send a connection lost event to the event bus, once per connection that announced itself.

        Gated on ``websocket_connected`` having reached the bus (``is_ready()`` never tracks the connection), so failed
        attempts, retries and ``before_shutdown`` emit no spurious or duplicate event. Bus errors are
        swallowed, so a bus failure cannot mask a network error.
        """
        if not self._bus_announced:
            return
        self._bus_announced = False
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)
        with suppress(Exception):
            await self.hassette.send_event(event)

    async def send_connection_established_event(self) -> None:
        """Send a connection established event to the event bus."""
        event = HassetteSimpleEvent.from_topic(topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)
        # Owed before the send: a drop handled while it is in flight must still pair with it.
        # Withdrawn if the event never gets out, cancellation by shutdown included.
        self._bus_announced = True
        try:
            await self.hassette.send_event(event)
        except BaseException:
            self._bus_announced = False
            raise
