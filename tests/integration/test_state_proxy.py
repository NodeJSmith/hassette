import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.core.state_proxy import StateCacheFreshness, StateProxy, StateSynchronizationStatus
from hassette.events import RawStateChangeEvent
from hassette.events.metadata import stamp_websocket_generation
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.lifecycle import mark_ready
from hassette.test_utils import make_full_state_change_event, make_light_state_dict, make_mock_hassette
from hassette.test_utils.ws_mocks import configure_ready_websocket_mock

# Generous bound for deterministic gate/task waits below — long enough to absorb slow CI,
# short enough to fail fast on a genuine hang instead of stalling the suite.
SYNC_WAIT_TIMEOUT = 1.0

# Short bound used only to prove a negative (e.g. "capability did not become ready in time").
# Long enough to rule out a race with the awaited coroutine; short because a correct assertion
# never needs to wait it out.
NO_SIGNAL_TIMEOUT = 0.05


def build_state_proxy(*, disable_state_proxy_polling: bool = True) -> StateProxy:
    hassette = make_mock_hassette(
        sealed=False,
        disable_state_proxy_polling=disable_state_proxy_polling,
        logging={"state_proxy": "DEBUG", "task_bucket": "DEBUG", "bus_service": "DEBUG"},
    )
    hassette.send_event = AsyncMock()
    hassette.api = Mock()
    hassette.api.get_states_raw = AsyncMock(return_value=[])
    hassette._websocket_service = Mock()
    hassette.websocket_service = hassette._websocket_service
    configure_ready_websocket_mock(hassette.websocket_service, generation=1)
    hassette.bus_service.add_listener = AsyncMock(return_value=1)
    hassette.bus_service.remove_listeners_by_owner.return_value = None
    proxy = StateProxy(hassette, parent=hassette)
    mark_ready(proxy.bus, reason="test bus ready")
    mark_ready(proxy.scheduler, reason="test scheduler ready")
    return proxy


def with_websocket_generation(event: RawStateChangeEvent, generation: int) -> RawStateChangeEvent:
    stamp_websocket_generation(event, generation)
    return event


@pytest.fixture
async def state_proxy() -> StateProxy:
    proxy = build_state_proxy()
    await proxy.on_initialize()
    yield proxy
    await proxy.on_shutdown()


async def test_successful_empty_snapshot_establishes_initial_capability(state_proxy: StateProxy) -> None:
    ready = await state_proxy.wait_initial_state_capability(timeout=SYNC_WAIT_TIMEOUT)

    assert ready is True
    assert state_proxy.is_ready() is True
    assert state_proxy.synchronization_status == StateSynchronizationStatus.IDLE
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.has_cache_entries is False
    assert state_proxy.has_initial_state_capability() is True


async def test_failed_initial_sync_keeps_cold_cache_blocked() -> None:
    proxy = build_state_proxy()
    proxy.hassette.api.get_states_raw.side_effect = RuntimeError("boom")

    await proxy.on_initialize()

    ready = await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT)

    assert ready is False
    assert proxy.is_ready() is True
    assert proxy.cache_freshness == StateCacheFreshness.UNAVAILABLE
    with pytest.raises(ResourceNotReadyError):
        proxy.get_state_once("light.kitchen")

    await proxy.on_shutdown()


async def test_repeated_sync_failure_for_same_generation_downgrades_to_warning() -> None:
    """First failure per generation logs a full traceback; repeats for that generation downgrade
    to a one-line WARNING, bounding log volume during an extended connected-but-failing outage.
    """
    proxy = build_state_proxy()
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("boom"))
    proxy.logger = Mock()

    await proxy.on_initialize()
    assert await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT) is False
    assert proxy.logger.exception.call_count == 1
    warning_count_after_first_failure = proxy.logger.warning.call_count

    # A second failure for the same (still-current) generation downgrades to WARNING.
    await proxy._run_synchronization(request_id=999, generation=1, status=StateSynchronizationStatus.RECONNECT)

    assert proxy.logger.exception.call_count == 1
    assert proxy.logger.warning.call_count == warning_count_after_first_failure + 1

    await proxy.on_shutdown()


async def test_pre_capability_event_does_not_unlock_partial_cold_cache() -> None:
    proxy = build_state_proxy()
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("boom"))
    await proxy.on_initialize()
    assert await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT) is False

    await proxy.on_state_change(
        make_full_state_change_event("light.kitchen", None, make_light_state_dict("light.kitchen", "on"))
    )

    assert proxy.states["light.kitchen"]["state"] == "on"
    assert proxy.cache_freshness == StateCacheFreshness.UNAVAILABLE
    with pytest.raises(ResourceNotReadyError):
        proxy.get_state_once("light.kitchen")

    await proxy.on_shutdown()


async def test_pre_capability_event_during_failed_initial_sync_keeps_cold_cache_blocked() -> None:
    proxy = build_state_proxy()
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def failing_snapshot() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        raise RuntimeError("boom")

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_snapshot)
    await proxy.on_initialize()
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    await proxy.on_state_change(
        make_full_state_change_event("light.kitchen", None, make_light_state_dict("light.kitchen", "on"))
    )
    release_snapshot.set()
    assert await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT) is False

    assert proxy.states["light.kitchen"]["state"] == "on"
    assert proxy.cache_freshness == StateCacheFreshness.UNAVAILABLE
    with pytest.raises(ResourceNotReadyError):
        proxy.get_state_once("light.kitchen")

    await proxy.on_shutdown()


async def test_duplicate_startup_and_connected_signals_coalesce_one_initial_sync() -> None:
    proxy = build_state_proxy()
    wait_entered = asyncio.Event()
    release_wait = asyncio.Event()
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def blocked_wait_initial_connection(*, timeout: float | None = None) -> bool:
        assert timeout == 1
        wait_entered.set()
        await release_wait.wait()
        return True

    async def gated_get_states_raw() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        return [make_light_state_dict("light.kitchen", "on")]

    proxy.hassette.websocket_service.wait_initial_connection = AsyncMock(side_effect=blocked_wait_initial_connection)
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=gated_get_states_raw)

    await proxy.on_initialize()
    await asyncio.wait_for(wait_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    reconnect_task = asyncio.create_task(proxy.on_reconnect())
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    release_wait.set()
    release_snapshot.set()
    await asyncio.wait_for(reconnect_task, timeout=SYNC_WAIT_TIMEOUT)
    ready = await proxy.wait_initial_state_capability(timeout=SYNC_WAIT_TIMEOUT)

    assert ready is True
    assert proxy.hassette.api.get_states_raw.await_count == 1
    assert proxy.cache_freshness == StateCacheFreshness.FRESH
    await proxy.on_shutdown()


async def test_duplicate_initial_signal_waiters_do_not_retry_immediately_after_failure() -> None:
    proxy = build_state_proxy()
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def failing_snapshot() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        raise RuntimeError("boom")

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_snapshot)

    await proxy.on_initialize()
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    reconnect_task = asyncio.create_task(proxy.on_reconnect())
    release_snapshot.set()
    await asyncio.wait_for(reconnect_task, timeout=SYNC_WAIT_TIMEOUT)

    assert proxy.hassette.api.get_states_raw.await_count == 1
    assert proxy.has_initial_state_capability() is False
    assert proxy._retry_task is not None

    await proxy.on_shutdown()


async def test_new_generation_is_not_lost_before_active_sync_is_initialized() -> None:
    proxy = build_state_proxy()
    begin_entered = asyncio.Event()
    release_begin = asyncio.Event()
    calls: list[int] = []
    original_begin = proxy._begin_synchronization

    async def gated_begin(*, request_id: int, generation: int, status: StateSynchronizationStatus) -> dict[str, object]:
        begin_entered.set()
        await release_begin.wait()
        return await original_begin(request_id=request_id, generation=generation, status=status)

    async def snapshot() -> list[dict[str, object]]:
        calls.append(proxy.hassette.websocket_service.get_connected_generation())
        return [make_light_state_dict("light.kitchen", "on")]

    proxy._begin_synchronization = gated_begin  # pyright: ignore[reportAttributeAccessIssue]
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=snapshot)

    task1 = asyncio.create_task(proxy.on_reconnect())
    await asyncio.wait_for(begin_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    task2 = asyncio.create_task(proxy.on_reconnect())
    release_begin.set()
    await asyncio.wait_for(asyncio.gather(task1, task2), timeout=SYNC_WAIT_TIMEOUT)

    assert calls == [2, 2]
    assert proxy.maintained_generation == 2
    assert proxy.cache_freshness == StateCacheFreshness.FRESH

    await proxy.on_shutdown()


async def test_poll_skips_during_active_sync_and_reconnect_afterward_runs_once(state_proxy: StateProxy) -> None:
    gate = asyncio.Event()
    sync_entered = asyncio.Event()
    calls: list[int] = []

    async def gated_get_states_raw() -> list[dict[str, object]]:
        calls.append(state_proxy.hassette.websocket_service.get_connected_generation())
        sync_entered.set()
        await gate.wait()
        return [make_light_state_dict("light.kitchen", "on")]

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=gated_get_states_raw)
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 1

    poll_task = asyncio.create_task(state_proxy.load_cache())
    await asyncio.wait_for(sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    await state_proxy.load_cache()
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    reconnect_task_1 = asyncio.create_task(state_proxy.on_reconnect())
    reconnect_task_2 = asyncio.create_task(state_proxy.on_reconnect())

    gate.set()
    await asyncio.wait_for(asyncio.gather(poll_task, reconnect_task_1, reconnect_task_2), timeout=SYNC_WAIT_TIMEOUT)

    assert calls == [1, 2]
    assert state_proxy.maintained_generation == 2
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH


async def test_obsolete_generation_sync_cannot_publish_freshness_or_capability() -> None:
    proxy = build_state_proxy()
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def gated_get_states_raw() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        return [make_light_state_dict("light.kitchen", "on")]

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=gated_get_states_raw)
    await proxy.on_initialize()
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    sync_task = proxy._sync_task
    assert sync_task is not None
    proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    release_snapshot.set()
    await asyncio.wait_for(sync_task, timeout=SYNC_WAIT_TIMEOUT)

    assert proxy.has_initial_state_capability() is False
    assert proxy.cache_freshness == StateCacheFreshness.UNAVAILABLE
    assert proxy.maintained_generation is None

    await proxy.on_shutdown()


async def test_obsolete_generation_failure_cannot_publish_freshness(state_proxy: StateProxy) -> None:
    state_proxy.states = {"light.kitchen": make_light_state_dict("light.kitchen", "on")}
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH

    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def failing_get_states_raw() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        raise RuntimeError("obsolete generation failed")

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_get_states_raw)
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 1

    sync_task = asyncio.create_task(state_proxy.load_cache())
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    release_snapshot.set()
    await asyncio.wait_for(sync_task, timeout=SYNC_WAIT_TIMEOUT)

    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.maintained_generation == 1


async def test_obsolete_generation_state_event_cannot_overwrite_fresh_cache(state_proxy: StateProxy) -> None:
    state_proxy.states = {"light.kitchen": make_light_state_dict("light.kitchen", "on")}
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH

    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2

    stale_event = with_websocket_generation(
        make_full_state_change_event(
            "light.kitchen",
            make_light_state_dict("light.kitchen", "on"),
            make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:10+00:00"),
        ),
        1,
    )

    await state_proxy.on_state_change(stale_event)

    assert state_proxy.states["light.kitchen"]["state"] == "on"
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH


async def test_journaled_updates_and_tombstones_win_over_snapshot(state_proxy: StateProxy) -> None:
    state_proxy.states = {
        "light.kitchen": make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:00+00:00"),
        "light.garage": make_light_state_dict("light.garage", "on", last_updated="2024-01-01T00:00:00+00:00"),
    }
    await state_proxy.on_disconnect()
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2

    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def gated_get_states_raw() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        return [
            make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:01+00:00"),
            make_light_state_dict("light.garage", "on", last_updated="2024-01-01T00:00:01+00:00"),
        ]

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=gated_get_states_raw)
    reconnect_task = asyncio.create_task(state_proxy.on_reconnect())
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    await state_proxy.on_state_change(
        make_full_state_change_event(
            "light.kitchen",
            state_proxy.states["light.kitchen"],
            make_light_state_dict("light.kitchen", "on", last_updated="2024-01-01T00:00:05+00:00"),
        )
    )
    await state_proxy.on_state_change(
        make_full_state_change_event("light.garage", state_proxy.states["light.garage"], None)
    )

    release_snapshot.set()
    await asyncio.wait_for(reconnect_task, timeout=SYNC_WAIT_TIMEOUT)

    assert state_proxy.states["light.kitchen"]["state"] == "on"
    assert "light.garage" not in state_proxy.states


async def test_pre_sync_state_event_does_not_overwrite_reconnect_snapshot(state_proxy: StateProxy) -> None:
    state_proxy.states = {
        "light.kitchen": make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:00+00:00")
    }
    stale_event = with_websocket_generation(
        make_full_state_change_event(
            "light.kitchen",
            state_proxy.states["light.kitchen"],
            make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:02+00:00"),
        ),
        generation=1,
    )

    await state_proxy.on_disconnect()
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def gated_snapshot() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        return [make_light_state_dict("light.kitchen", "on", last_updated="2024-01-01T00:00:01+00:00")]

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=gated_snapshot)
    reconnect_task = asyncio.create_task(state_proxy.on_reconnect())
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    await state_proxy.on_state_change(stale_event)
    release_snapshot.set()
    await asyncio.wait_for(reconnect_task, timeout=SYNC_WAIT_TIMEOUT)

    assert state_proxy.states["light.kitchen"]["state"] == "on"
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.maintained_generation == 2


async def test_fresher_snapshot_replaces_older_cached_state(state_proxy: StateProxy) -> None:
    state_proxy.states = {
        "light.kitchen": make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:00+00:00")
    }
    state_proxy.hassette.api.get_states_raw = AsyncMock(
        return_value=[make_light_state_dict("light.kitchen", "on", last_updated="2024-01-01T00:00:01+00:00")]
    )

    await state_proxy.load_cache()

    assert state_proxy.states["light.kitchen"]["state"] == "on"


async def test_disconnect_preserves_stale_reads_and_reconnect_failure_keeps_listener(state_proxy: StateProxy) -> None:
    state_proxy.states["light.kitchen"] = make_light_state_dict("light.kitchen", "on")

    await state_proxy.on_disconnect()

    assert state_proxy.cache_freshness == StateCacheFreshness.STALE
    assert state_proxy.get_state_once("light.kitchen") is not None
    assert state_proxy.state_change_sub is not None

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("boom"))
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    await state_proxy.on_reconnect()

    assert state_proxy.state_change_sub is not None
    assert state_proxy.cache_freshness == StateCacheFreshness.STALE


async def test_retry_failure_schedules_next_generation_scoped_retry() -> None:
    proxy = build_state_proxy()
    proxy._compute_retry_delay = Mock(side_effect=[0, 60])  # pyright: ignore[reportAttributeAccessIssue]
    first_sync_entered = asyncio.Event()
    call_count = 0

    async def failing_get_states_raw() -> list[dict[str, object]]:
        nonlocal call_count
        call_count += 1
        first_sync_entered.set()
        raise RuntimeError(f"boom-{call_count}")

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_get_states_raw)

    await proxy.on_initialize()
    await asyncio.wait_for(first_sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    first_retry = proxy._retry_task
    assert first_retry is not None
    await asyncio.wait_for(first_retry, timeout=SYNC_WAIT_TIMEOUT)

    assert proxy._retry_task is not None
    assert proxy._retry_task is not first_retry
    assert [call.args[0] for call in proxy._compute_retry_delay.call_args_list] == [1, 2]

    await proxy.on_shutdown()


async def test_retry_attempt_resets_when_generation_changes() -> None:
    proxy = build_state_proxy()
    proxy._compute_retry_delay = Mock(return_value=60)  # pyright: ignore[reportAttributeAccessIssue]
    first_sync_entered = asyncio.Event()

    async def failing_initial_snapshot() -> list[dict[str, object]]:
        first_sync_entered.set()
        raise RuntimeError("boom-1")

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_initial_snapshot)
    await proxy.on_initialize()
    await asyncio.wait_for(first_sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    assert proxy._bootstrap_task is not None
    await asyncio.wait_for(proxy._bootstrap_task, timeout=SYNC_WAIT_TIMEOUT)

    proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("boom-2"))

    await proxy.on_reconnect()

    assert [call.args[0] for call in proxy._compute_retry_delay.call_args_list] == [1, 1]

    await proxy.on_shutdown()


async def test_poll_enabled_initial_failure_converges_through_next_poll() -> None:
    proxy = build_state_proxy(disable_state_proxy_polling=False)
    first_sync_entered = asyncio.Event()

    async def initial_then_successful_snapshot() -> list[dict[str, object]]:
        if not first_sync_entered.is_set():
            first_sync_entered.set()
            raise RuntimeError("boom")
        return [make_light_state_dict("light.kitchen", "on")]

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=initial_then_successful_snapshot)

    await proxy.on_initialize()
    await asyncio.wait_for(first_sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    assert await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT) is False

    await proxy.load_cache()

    assert await proxy.wait_initial_state_capability(timeout=SYNC_WAIT_TIMEOUT) is True
    assert proxy.hassette.api.get_states_raw.await_count == 2
    assert proxy.cache_freshness == StateCacheFreshness.FRESH
    assert proxy.maintained_generation == 1

    await proxy.on_shutdown()


async def test_poll_enabled_reconnect_failure_converges_through_next_poll(state_proxy: StateProxy) -> None:
    state_proxy.states = {"light.kitchen": make_light_state_dict("light.kitchen", "on")}
    state_proxy.poll_job = Mock()
    await state_proxy.on_disconnect()

    snapshot_calls = 0

    async def reconnect_then_successful_snapshot() -> list[dict[str, object]]:
        nonlocal snapshot_calls
        snapshot_calls += 1
        if snapshot_calls == 1:
            raise RuntimeError("boom")
        return [make_light_state_dict("light.kitchen", "off")]

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=reconnect_then_successful_snapshot)
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2

    await state_proxy.on_reconnect()

    assert state_proxy.cache_freshness == StateCacheFreshness.STALE
    assert state_proxy.maintained_generation is None or state_proxy.maintained_generation == 1

    await state_proxy.load_cache()

    assert snapshot_calls == 2
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.maintained_generation == 2


async def test_duplicate_reconnect_waiters_do_not_retry_immediately_after_failure(state_proxy: StateProxy) -> None:
    state_proxy.states = {"light.kitchen": make_light_state_dict("light.kitchen", "on")}
    await state_proxy.on_disconnect()
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    snapshot_entered = asyncio.Event()
    release_snapshot = asyncio.Event()

    async def failing_snapshot() -> list[dict[str, object]]:
        snapshot_entered.set()
        await release_snapshot.wait()
        raise RuntimeError("boom")

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_snapshot)

    reconnect_task_1 = asyncio.create_task(state_proxy.on_reconnect())
    await asyncio.wait_for(snapshot_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    reconnect_task_2 = asyncio.create_task(state_proxy.on_reconnect())
    release_snapshot.set()
    await asyncio.wait_for(asyncio.gather(reconnect_task_1, reconnect_task_2), timeout=SYNC_WAIT_TIMEOUT)

    assert state_proxy.hassette.api.get_states_raw.await_count == 1
    assert state_proxy.cache_freshness == StateCacheFreshness.STALE
    assert state_proxy._retry_task is not None


async def test_disconnect_cancels_active_sync_so_reconnect_can_start_fresh(state_proxy: StateProxy) -> None:
    sync_entered = asyncio.Event()
    never_release = asyncio.Event()

    async def blocked_snapshot() -> list[dict[str, object]]:
        sync_entered.set()
        await never_release.wait()
        return [make_light_state_dict("light.kitchen", "on")]

    state_proxy.hassette.api.get_states_raw = AsyncMock(side_effect=blocked_snapshot)
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 1

    poll_task = asyncio.create_task(state_proxy.load_cache())
    await asyncio.wait_for(sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)

    await state_proxy.on_disconnect()
    assert state_proxy._sync_task is None

    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    state_proxy.hassette.api.get_states_raw = AsyncMock(return_value=[make_light_state_dict("light.kitchen", "off")])

    await asyncio.wait_for(state_proxy.on_reconnect(), timeout=SYNC_WAIT_TIMEOUT)
    await asyncio.gather(poll_task, return_exceptions=True)

    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.maintained_generation == 2


async def test_superseded_retry_task_is_canceled_when_new_generation_sync_starts() -> None:
    proxy = build_state_proxy()
    retry_started = asyncio.Event()
    first_sync_entered = asyncio.Event()
    original_schedule_retry = proxy._schedule_retry

    async def failing_snapshot() -> list[dict[str, object]]:
        first_sync_entered.set()
        raise RuntimeError("boom")

    async def observed_schedule_retry(_generation: int) -> None:
        retry_started.set()

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_snapshot)
    proxy._compute_retry_delay = Mock(return_value=60)  # pyright: ignore[reportAttributeAccessIssue]
    proxy._schedule_retry = observed_schedule_retry  # pyright: ignore[reportAttributeAccessIssue]

    await proxy.on_initialize()
    await asyncio.wait_for(first_sync_entered.wait(), timeout=SYNC_WAIT_TIMEOUT)
    await asyncio.wait_for(retry_started.wait(), timeout=SYNC_WAIT_TIMEOUT)
    proxy._schedule_retry = original_schedule_retry  # pyright: ignore[reportAttributeAccessIssue]
    await original_schedule_retry(1)

    first_retry = proxy._retry_task
    assert first_retry is not None

    proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    proxy.hassette.api.get_states_raw = AsyncMock(return_value=[make_light_state_dict("light.kitchen", "on")])

    await proxy.on_reconnect()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(first_retry, timeout=SYNC_WAIT_TIMEOUT)

    assert proxy.has_initial_state_capability() is True
    assert proxy.maintained_generation == 2

    await proxy.on_shutdown()
