"""serve()'s reconnect loop, driven against a scripted Home Assistant WebSocket server.

Pins design/specs/131-ha-restart-reconnect: failures retry in place and never leave serve()
(D1, D9), a rejected token is retried three times, then parks (D3, D10), the connection waits for HA's
RUNNING core state before advertising CONNECTED (D12), oversized messages escalate to the Slow pace (D13), a
dead receive loop fails pending replies at once, and the bus connection events alternate, connected first, even when
the connection drops or shutdown lands while connected observers run. Backoff delays are shrunk via the
``fast_reconnect`` fixture; classification and pacing values are pinned in
tests/unit/core/test_websocket_reconnect.py.

Complements test_reconnect.py (partial_cleanup and the connection-lost event).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiohttp
import pytest

import hassette.core.websocket_reconnect as reconnect_module
import hassette.core.websocket_service as websocket_service_module
from hassette.core.websocket_reconnect import (
    AUTH_REJECTED_REASON,
    CONNECTED_REASON,
    CORE_NOT_RUNNING_REASON,
    NOT_CONNECTED_REASON,
    Disposition,
    RetryPlan,
)
from hassette.core.websocket_service import WebsocketService
from hassette.exceptions import InvalidLifecycleTransitionError, ResponseLostError
from hassette.testing import EventCapture, wait_for
from hassette.types import Topic
from hassette.types.enums import ConnectionState
from tests.support.fake_ha_ws import FakeHomeAssistant

WAIT_SECONDS = 5.0
SLOW_TEST_DELAY_SECONDS = 0.05
"""Stands in for the 5-minute Slow pace, distinct from the shrunk Fast cap so plans can tell them apart."""


@pytest.fixture
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_INITIAL_SECONDS", 0.001)
    monkeypatch.setattr(reconnect_module, "FAST_BACKOFF_CAP_SECONDS", 0.01)
    monkeypatch.setattr(reconnect_module, "AUTH_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(reconnect_module, "SLOW_RETRY_SECONDS", SLOW_TEST_DELAY_SECONDS)
    monkeypatch.setattr(websocket_service_module, "CORE_RUNNING_RECHECK_SECONDS", 0.05)


@pytest.fixture
async def fake_ha() -> AsyncIterator[FakeHomeAssistant]:
    server = FakeHomeAssistant()
    await server.start()
    yield server
    await server.stop()


@asynccontextmanager
async def serving(websocket_service: WebsocketService, fake_ha: FakeHomeAssistant) -> AsyncIterator[asyncio.Task]:
    """Run serve() against ``fake_ha`` and tear it down afterwards."""
    websocket_service.url = fake_ha.url
    task = asyncio.create_task(websocket_service.serve())
    try:
        yield task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await websocket_service.partial_cleanup()


def record_plans(websocket_service: WebsocketService) -> list[RetryPlan]:
    """Collect every plan handle_connection_failure() returns, in order."""
    plans: list[RetryPlan] = []
    original = websocket_service.handle_connection_failure

    async def recording(exc: Exception) -> RetryPlan:
        plan = await original(exc)
        plans.append(plan)
        return plan

    websocket_service.handle_connection_failure = recording  # pyright: ignore[reportAttributeAccessIssue]
    return plans


async def wait_connected(websocket_service: WebsocketService) -> int:
    generation = await websocket_service.wait_connected_generation(timeout=WAIT_SECONDS)
    assert generation is not None, f"never reached CONNECTED (state {websocket_service.connection_state})"
    return generation


@pytest.mark.usefixtures("fast_reconnect")
async def test_refused_connection_retries_until_ha_appears(websocket_service: WebsocketService) -> None:
    """Connection refused (HA down at startup) retries in place, then connects once HA listens."""
    fake_ha = FakeHomeAssistant()
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha) as task:
        await wait_for(lambda: len(plans) >= 3, timeout=WAIT_SECONDS, desc="refused attempts retried")
        assert not task.done()
        assert websocket_service.connection_state == ConnectionState.CONNECTING
        assert {plan.disposition for plan in plans} == {Disposition.FAST}

        await fake_ha.start()
        try:
            await wait_connected(websocket_service)
        finally:
            await fake_ha.stop()


@pytest.mark.usefixtures("fast_reconnect")
async def test_ha_restart_reconnects_in_the_same_serve_call(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """An HA restart (1001 close, then refused, then back) reconnects without serve() returning or raising."""
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    await websocket_service.on_initialize()

    async with serving(websocket_service, fake_ha) as task:
        first_generation = await wait_connected(websocket_service)
        assert websocket_service._ready_reason == CONNECTED_REASON

        await fake_ha.stop()
        await wait_for(lambda: not websocket_service.is_connected, timeout=WAIT_SECONDS, desc="drop detected")
        assert websocket_service.is_ready()
        await wait_for(
            lambda: websocket_service._ready_reason == NOT_CONNECTED_REASON, timeout=WAIT_SECONDS, desc="reason"
        )

        await fake_ha.start()
        second_generation = await wait_connected(websocket_service)

        assert second_generation > first_generation
        assert not task.done()
        assert websocket_service.is_ready()
        assert websocket_service._ready_reason == CONNECTED_REASON
        assert len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED)) == 1
        assert len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)) == 2


@pytest.mark.usefixtures("fast_reconnect")
@pytest.mark.parametrize(
    "status",
    [
        pytest.param(502, id="supervisor-proxy-while-core-restarts"),
        pytest.param(404, id="reverse-proxy-backend-stopped"),
    ],
)
async def test_restart_handshake_status_retries_at_fast_pace(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant, status: int
) -> None:
    """A proxy's 502 or 404 while HA restarts behind it heals on its own, so it is Fast, not Slow."""
    fake_ha.handshake_status = status
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha):
        await wait_for(lambda: len(plans) >= 3, timeout=WAIT_SECONDS, desc=f"{status} attempts retried")
        assert {plan.disposition for plan in plans} == {Disposition.FAST}

        fake_ha.handshake_status = None
        await wait_connected(websocket_service)


@pytest.mark.usefixtures("fast_reconnect")
async def test_unresolvable_host_retries_at_fast_pace(
    websocket_service: WebsocketService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A DNS failure (HA's host not resolvable yet, e.g. after a router reboot) is Fast, not Slow."""
    key = aiohttp.client_reqrep.ConnectionKey("ha-host.invalid", 8123, False, None, None, None, None)

    async def fail_resolution(*_args: Any, **_kwargs: Any) -> None:
        raise aiohttp.ClientConnectorDNSError(key, OSError("name resolution failed"))

    # Raise the resolver's error directly: a real lookup depends on the runner's DNS behaving.
    monkeypatch.setattr(aiohttp.ClientSession, "ws_connect", fail_resolution)
    plans = record_plans(websocket_service)

    task = asyncio.create_task(websocket_service.serve())
    try:
        await wait_for(lambda: len(plans) >= 2, timeout=WAIT_SECONDS, desc="DNS failures retried")
        assert {plan.disposition for plan in plans} == {Disposition.FAST}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await websocket_service.partial_cleanup()


@pytest.mark.usefixtures("fast_reconnect")
async def test_handshake_401_retries_at_slow_pace(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A reverse proxy's 401 is retried at the Slow pace, never parked."""
    fake_ha.handshake_status = 401
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha) as task:
        await wait_for(lambda: len(plans) >= 2, timeout=WAIT_SECONDS, desc="401 attempts retried")
        assert {plan.disposition for plan in plans} == {Disposition.SLOW}
        assert {plan.delay for plan in plans} == {SLOW_TEST_DELAY_SECONDS}
        assert not task.done()


@pytest.mark.usefixtures("fast_reconnect")
async def test_auth_rejected_before_any_connection_retries_three_times_then_parks(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A token that never worked gets the same 3 spaced retries (4 logins), then parks without leaving serve()."""
    fake_ha.auth_valid = False
    plans = record_plans(websocket_service)
    await websocket_service.on_initialize()

    async with serving(websocket_service, fake_ha) as task:
        await wait_for(
            lambda: websocket_service.connection_state == ConnectionState.AUTH_FAILED,
            timeout=WAIT_SECONDS,
            desc="parked on auth_invalid",
        )
        await asyncio.sleep(0.1)  # ample time for further attempts at the shrunk pace, were any made

        assert fake_ha.auth_attempts == 4
        assert [plan.disposition for plan in plans] == [Disposition.AUTH_RETRY] * 3 + [Disposition.PARK]
        assert not task.done()
        assert websocket_service.is_ready()
        assert websocket_service._ready_reason == AUTH_REJECTED_REASON


@pytest.mark.usefixtures("fast_reconnect")
async def test_shutdown_while_parked_ends_serve_and_keeps_the_park_reason(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Cancelling serve() at shutdown ends the park, and the late status reports do not overwrite the reason."""
    fake_ha.auth_valid = False
    await websocket_service.on_initialize()

    async with serving(websocket_service, fake_ha) as task:
        await wait_for(
            lambda: websocket_service.connection_state == ConnectionState.AUTH_FAILED,
            timeout=WAIT_SECONDS,
            desc="parked",
        )
        websocket_service.shutdown_event.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

        assert task.cancelled()
        await websocket_service.report_connection_status(NOT_CONNECTED_REASON)
        assert websocket_service._ready_reason == AUTH_REJECTED_REASON


@pytest.mark.usefixtures("fast_reconnect")
async def test_auth_rejected_after_prior_success_retries_three_times_then_parks(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A previously working token gets 3 spaced retries (4 logins in all), then parks."""
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha) as task:
        await wait_connected(websocket_service)
        fake_ha.auth_valid = False
        await fake_ha.drop_all()

        await wait_for(
            lambda: websocket_service.connection_state == ConnectionState.AUTH_FAILED,
            timeout=WAIT_SECONDS,
            desc="parked after auth retries",
        )
        await asyncio.sleep(0.1)

        assert fake_ha.auth_attempts == 1 + 4
        assert [plan.disposition for plan in plans if plan.disposition is not Disposition.FAST] == [
            Disposition.AUTH_RETRY,
            Disposition.AUTH_RETRY,
            Disposition.AUTH_RETRY,
            Disposition.PARK,
        ]
        assert not task.done()


@pytest.mark.usefixtures("fast_reconnect")
async def test_running_gate_holds_connecting_and_drops_events_until_ha_started(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """While HA is STARTING the connection stays CONNECTING, drops events, and connects on homeassistant_started."""
    fake_ha.core_states = ["STARTING"]
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    async with serving(websocket_service, fake_ha):
        await wait_for(lambda: fake_ha.get_config_calls >= 1, timeout=WAIT_SECONDS, desc="core state read")
        await wait_for(
            lambda: websocket_service._ready_reason == CORE_NOT_RUNNING_REASON.format("STARTING"),
            timeout=WAIT_SECONDS,
            desc="waiting reason recorded",
        )
        assert websocket_service.connection_state == ConnectionState.CONNECTING

        await fake_ha.send_event("state_changed", {"entity_id": "light.kitchen", "new_state": None})
        await fake_ha.send_event("homeassistant_started")
        await wait_connected(websocket_service)

        assert capture.by_topic(Topic.HASS_EVENT_STATE_CHANGED) == []


@pytest.mark.usefixtures("fast_reconnect")
async def test_started_event_caught_by_the_gate_is_dispatched_once_after_connected(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """homeassistant_started ends the gate, then reaches the bus exactly once, after WEBSOCKET_CONNECTED."""
    fake_ha.core_states = ["STARTING"]
    capture = EventCapture()
    capture.install(websocket_service.hassette)

    async with serving(websocket_service, fake_ha):
        await wait_for(lambda: fake_ha.get_config_calls >= 1, timeout=WAIT_SECONDS, desc="core state read")
        await fake_ha.send_event("homeassistant_started")
        await wait_connected(websocket_service)
        await wait_for(
            lambda: any(str(t).endswith("homeassistant_started") for t in capture.topics),
            timeout=WAIT_SECONDS,
            desc="held event dispatched",
        )
        await asyncio.sleep(0.1)

    topics = [str(topic) for topic in capture.topics]
    started = [i for i, topic in enumerate(topics) if topic.endswith("homeassistant_started")]
    connected = topics.index(str(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED))
    assert len(started) == 1
    assert started[0] > connected


@pytest.mark.usefixtures("fast_reconnect")
async def test_running_gate_rechecks_core_state_when_started_event_is_missed(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Without homeassistant_started, the gate re-reads get_config and connects once it reports RUNNING."""
    fake_ha.core_states = ["STARTING", "STARTING", "RUNNING"]

    async with serving(websocket_service, fake_ha):
        await wait_connected(websocket_service)

    assert fake_ha.get_config_calls == 3


@pytest.mark.usefixtures("fast_reconnect")
async def test_shutting_down_core_state_backs_off_and_reconnects(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """HA reporting STOPPING during the gate closes that attempt and retries at the Fast pace."""
    fake_ha.core_states = ["STOPPING"]
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha):
        await wait_for(lambda: len(plans) >= 2, timeout=WAIT_SECONDS, desc="STOPPING attempts retried")
        assert {plan.disposition for plan in plans} == {Disposition.FAST}
        assert websocket_service.connection_state == ConnectionState.CONNECTING

        fake_ha.core_states = ["RUNNING"]
        await wait_connected(websocket_service)


@pytest.mark.usefixtures("fast_reconnect")
async def test_drop_during_running_wait_retries_and_replaces_the_waiting_reason(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A socket lost while waiting for RUNNING retries in place, and the stale waiting reason is replaced."""
    fake_ha.core_states = ["STARTING"]
    plans = record_plans(websocket_service)

    async with serving(websocket_service, fake_ha) as task:
        await wait_for(lambda: fake_ha.get_config_calls >= 1, timeout=WAIT_SECONDS, desc="core state read")
        await fake_ha.stop()

        await wait_for(lambda: len(plans) >= 1, timeout=WAIT_SECONDS, desc="drop handled")
        assert websocket_service._ready_reason == NOT_CONNECTED_REASON
        assert not task.done()

        fake_ha.core_states = ["RUNNING"]
        await fake_ha.start()
        await wait_connected(websocket_service)


@pytest.mark.usefixtures("fast_reconnect")
async def test_oversized_get_states_on_three_consecutive_connections_moves_to_slow(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A get_states reply over the size limit (sent after CONNECTED, as StateProxy does) escalates to Slow."""
    monkeypatch.setattr(websocket_service_module, "WS_MAX_MSG_SIZE", 1024)
    fake_ha.get_states_payload = [{"entity_id": f"sensor.s{i}", "state": "x" * 100} for i in range(50)]
    plans = record_plans(websocket_service)

    async def fetch_states(_generation: int) -> None:
        await websocket_service.send_and_wait(type="get_states")

    websocket_service.connected_observers.add(fetch_states)

    async with serving(websocket_service, fake_ha):
        await wait_for(lambda: len(plans) >= 4, timeout=WAIT_SECONDS, desc="oversize attempts retried")

    assert [plan.disposition for plan in plans[:4]] == [
        Disposition.FAST,
        Disposition.FAST,
        Disposition.SLOW,
        Disposition.SLOW,
    ]
    assert fake_ha.connections >= 4


@pytest.mark.usefixtures("fast_reconnect")
async def test_pending_reply_fails_the_moment_the_connection_drops(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A caller awaiting a reply gets ResponseLostError on the drop, not after the response timeout."""
    fake_ha.unanswered_commands = {"get_services"}

    async with serving(websocket_service, fake_ha):
        await wait_connected(websocket_service)
        pending = asyncio.create_task(websocket_service.send_and_wait(type="get_services"))
        await wait_for(lambda: len(websocket_service._pending.entries) == 1, timeout=WAIT_SECONDS, desc="sent")

        await fake_ha.drop_all()

        with pytest.raises(ResponseLostError):
            await asyncio.wait_for(pending, timeout=1.0)


@pytest.mark.usefixtures("fast_reconnect")
async def test_drop_during_connected_observers_still_pairs_connected_then_disconnected(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """A drop while a connected observer runs is announced, not suppressed: connected, then disconnected.

    The bus events promise pairing and order, not that the connection is still up on delivery
    (design/research/2026-10-12-connect-announcement-contract/prior-art.md).
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    dropped = False

    async def drop_on_first_connect(generation: int) -> None:  # noqa: ARG001
        nonlocal dropped
        if dropped:
            return
        dropped = True
        await fake_ha.drop_all()
        await wait_for(lambda: not websocket_service.is_connected, timeout=WAIT_SECONDS, desc="drop detected")

    websocket_service.connected_observers.add(drop_on_first_connect)

    async with serving(websocket_service, fake_ha):
        await wait_for(
            lambda: len(capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED)) >= 2,
            timeout=WAIT_SECONDS,
            desc="reconnected after the mid-announcement drop",
        )

    connection_topics = {Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED, Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED}
    assert [topic for topic in capture.topics if topic in connection_topics][:3] == [
        Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
        Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED,
        Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
    ]


@pytest.mark.usefixtures("fast_reconnect")
async def test_shutdown_during_connected_observers_emits_no_unpaired_disconnected(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Shutdown before websocket_connected reaches the bus sends no websocket_disconnected either.

    The connected observers were notified, so the disconnected observers still run: the two
    pairs are tracked separately.
    """
    capture = EventCapture()
    capture.install(websocket_service.hassette)
    observer_entered = asyncio.Event()
    disconnected_notified: list[None] = []

    async def parked_observer(generation: int) -> None:  # noqa: ARG001
        observer_entered.set()
        await asyncio.Event().wait()  # never set: only shutdown's cancellation ends it

    async def record_disconnect() -> None:
        disconnected_notified.append(None)

    websocket_service.connected_observers.add(parked_observer)
    websocket_service.disconnected_observers.add(record_disconnect)

    async with serving(websocket_service, fake_ha):
        await asyncio.wait_for(observer_entered.wait(), timeout=WAIT_SECONDS)

    await websocket_service.before_shutdown()

    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED) == []
    assert capture.by_topic(Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED) == []
    assert len(disconnected_notified) == 1


async def test_invalid_lifecycle_transition_propagates_out_of_serve(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Strict-mode lifecycle bugs are never retried: they leave serve() and fail the test that hit them."""

    async def broken_connection(_session: Any) -> None:
        raise InvalidLifecycleTransitionError(
            from_status=ConnectionState.CONNECTED, to_status=ConnectionState.CONNECTED, resource_name="test"
        )

    websocket_service.run_connection = broken_connection  # pyright: ignore[reportAttributeAccessIssue]

    async with serving(websocket_service, fake_ha) as task:
        with pytest.raises(InvalidLifecycleTransitionError):
            await asyncio.wait_for(task, timeout=WAIT_SECONDS)


class FastSleepAsyncio:
    """Stands in for the ``asyncio`` module inside websocket_service: ``sleep`` yields instead of waiting."""

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    @staticmethod
    async def sleep(_delay: float) -> None:
        await asyncio.sleep(0.01)


async def test_repeated_accept_then_drop_cycles_keep_backing_off_up_to_the_fast_cap(
    monkeypatch: pytest.MonkeyPatch, websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Connections that reach CONNECTED but drop within seconds are flaps: the delay grows to 5 s and stays there.

    Runs with the real Fast constants; only serve()'s sleep is shortened, so the recorded plan delays are the
    production curve. A connect that reset the curve would show ~1 s delays all the way through.
    """
    monkeypatch.setattr(websocket_service_module, "asyncio", FastSleepAsyncio())
    plans = record_plans(websocket_service)
    cycles = 7

    async with serving(websocket_service, fake_ha):
        for cycle in range(1, cycles + 1):
            await wait_for(lambda n=cycle: fake_ha.connections >= n, timeout=WAIT_SECONDS, desc=f"connection {cycle}")
            await wait_connected(websocket_service)
            await fake_ha.drop_all()
            await wait_for(lambda n=cycle: len(plans) >= n, timeout=WAIT_SECONDS, desc=f"drop {cycle} handled")

    delays = [plan.delay for plan in plans[:cycles]]
    assert all(plan.disposition is Disposition.FAST for plan in plans[:cycles])
    assert all(delay is not None and delay <= reconnect_module.FAST_BACKOFF_CAP_SECONDS for delay in delays)
    assert delays[0] is not None
    assert delays[0] <= 1.2
    assert all(delay is not None and delay >= 3.2 for delay in delays[2:]), delays
    assert delays[3:] == [reconnect_module.FAST_BACKOFF_CAP_SECONDS] * (cycles - 3)


@pytest.mark.usefixtures("fast_reconnect")
async def test_shutdown_while_receiving_ends_the_recv_task_without_an_error(
    websocket_service: WebsocketService, fake_ha: FakeHomeAssistant
) -> None:
    """Shutdown cancelling serve() closes the socket under a blocked receive(); the recv task ends quietly (#2757)."""
    receiving = asyncio.Event()  # set each time the recv loop blocks in receive(), so shutdown lands mid-receive
    original_receive = aiohttp.ClientWebSocketResponse.receive

    async def signalling_receive(ws: aiohttp.ClientWebSocketResponse, *args: Any, **kwargs: Any) -> aiohttp.WSMessage:
        receiving.set()
        return await original_receive(ws, *args, **kwargs)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(aiohttp.ClientWebSocketResponse, "receive", signalling_receive)
        async with serving(websocket_service, fake_ha) as task:
            await wait_connected(websocket_service)
            recv_task = websocket_service._recv_task
            assert recv_task is not None
            receiving.clear()
            await fake_ha.send_event("noop_event")  # recv loop handles it, then blocks in receive() again
            await asyncio.wait_for(receiving.wait(), timeout=WAIT_SECONDS)

            websocket_service.shutdown_event.set()
            task.cancel()
            await asyncio.gather(task, recv_task, return_exceptions=True)

    assert not recv_task.cancelled(), "the socket close must reach the recv task before any cancellation"
    assert recv_task.exception() is None, "a recv task that raises is reported by TaskBucket as a crash"
