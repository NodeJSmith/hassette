import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from unittest.mock import AsyncMock, Mock

import pytest

from hassette.config.config import HassetteConfig
from hassette.core.state_proxy import StateCacheFreshness, StateProxy, StateSynchronizationStatus
from hassette.events import RawStateChangeEvent
from hassette.events.metadata import stamp_websocket_generation
from hassette.exceptions import ResourceNotReadyError
from hassette.resources.lifecycle import mark_ready
from hassette.testing import HassetteHarness, build_harness, make_full_state_change_event, make_light_state_dict
from tests.support.mock_hassette import TEST_TOTAL_TIMEOUT_SECONDS, make_mock_hassette
from tests.support.web_mocks import configure_ready_websocket_mock

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


def gated_get_states_raw_factory(
    result: list[dict[str, object]] | None = None,
    error: Exception | None = None,
) -> tuple[asyncio.Event, asyncio.Event, Callable[[], Awaitable[list[dict[str, object]]]]]:
    """Build a gated ``api.get_states_raw`` side effect for ``AsyncMock(side_effect=...)``.

    Collapses the repeated snapshot_entered/release_snapshot gate scaffold duplicated across
    this file's reconnect/retry tests (issue #1493) into one helper.

    Returns ``(entered, release, side_effect)``: ``entered`` is set the moment the side effect
    starts running — await it to know the snapshot call has begun. The side effect then blocks
    on ``release`` (call ``.set()`` to let it proceed) before returning ``result`` (default
    ``[]``) or raising ``error`` if given. If ``release`` is never set, the call blocks
    forever — useful for tests that assert on cancellation rather than completion.
    """
    entered = asyncio.Event()
    release = asyncio.Event()

    async def side_effect() -> list[dict[str, object]]:
        entered.set()
        await release.wait()
        if error is not None:
            raise error
        return result if result is not None else []

    return entered, release, side_effect


@pytest.fixture
async def state_proxy() -> AsyncIterator[StateProxy]:
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
    A failure for a genuinely new generation resets the gate, so that generation's first failure
    logs a full traceback again instead of staying downgraded forever.
    """
    proxy = build_state_proxy()
    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=RuntimeError("boom"))

    await proxy.on_initialize()
    assert await proxy.wait_initial_state_capability(timeout=NO_SIGNAL_TIMEOUT) is False

    # `_last_logged_sync_failure_generation` is the exact state that decides full-traceback vs.
    # downgraded-warning logging (see _run_synchronization's except block), so asserting on it
    # is a direct proxy for that behavior without mocking the logger.
    assert proxy._last_logged_sync_failure_generation == 1

    # A second failure for the same (still-current) generation is a repeat: the gate value is
    # unchanged, proving the code took the "already logged for this generation" (warning) branch
    # rather than the full-traceback branch, which would have re-recorded the same generation.
    await proxy._run_synchronization(request_id=999, generation=1, status=StateSynchronizationStatus.RECONNECT)
    assert proxy._last_logged_sync_failure_generation == 1

    # A failure for a different generation updates the gate, proving that generation is tracked
    # fresh and would get full-traceback treatment again rather than staying downgraded forever.
    await proxy._run_synchronization(request_id=1000, generation=2, status=StateSynchronizationStatus.RECONNECT)
    assert proxy._last_logged_sync_failure_generation == 2

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
    snapshot_entered, release_snapshot, failing_snapshot = gated_get_states_raw_factory(error=RuntimeError("boom"))

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

    async def blocked_wait_initial_connection(*, timeout: float | None = None) -> bool:
        assert timeout == TEST_TOTAL_TIMEOUT_SECONDS
        wait_entered.set()
        await release_wait.wait()
        return True

    snapshot_entered, release_snapshot, gated_get_states_raw = gated_get_states_raw_factory(
        result=[make_light_state_dict("light.kitchen", "on")]
    )

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
    snapshot_entered, release_snapshot, failing_snapshot = gated_get_states_raw_factory(error=RuntimeError("boom"))

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
    snapshot_entered, release_snapshot, gated_get_states_raw = gated_get_states_raw_factory(
        result=[make_light_state_dict("light.kitchen", "on")]
    )

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

    snapshot_entered, release_snapshot, failing_get_states_raw = gated_get_states_raw_factory(
        error=RuntimeError("obsolete generation failed")
    )

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

    snapshot_entered, release_snapshot, gated_get_states_raw = gated_get_states_raw_factory(
        result=[
            make_light_state_dict("light.kitchen", "off", last_updated="2024-01-01T00:00:01+00:00"),
            make_light_state_dict("light.garage", "on", last_updated="2024-01-01T00:00:01+00:00"),
        ]
    )

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
    snapshot_entered, release_snapshot, gated_snapshot = gated_get_states_raw_factory(
        result=[make_light_state_dict("light.kitchen", "on", last_updated="2024-01-01T00:00:01+00:00")]
    )

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
    call_count = 0
    original_schedule_retry = proxy._schedule_retry
    first_retry_scheduled = asyncio.Event()
    first_retry_task: asyncio.Task[None] | None = None

    async def failing_get_states_raw() -> list[dict[str, object]]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError(f"boom-{call_count}")

    # The first real retry uses a 0s delay (per _compute_retry_delay's side_effect above), so it
    # can run to completion and schedule a *second* retry task before the test task gets a chance
    # to resume from `first_retry_scheduled.wait()` — that's the exact race this test used to hit
    # in CI. Capturing `proxy._retry_task` into `first_retry_task` *inside* the wrapper, in the
    # same coroutine step that assigns it, is what actually closes the window; reading
    # `proxy._retry_task` after the event fires (outside the wrapper) does not, since the second
    # retry may have already superseded it by then. The `is None` guard keeps the second
    # invocation (for the 60s-delay retry) from overwriting the captured first task.
    async def observed_schedule_retry(generation: int) -> None:
        nonlocal first_retry_task
        await original_schedule_retry(generation)
        if first_retry_task is None:
            first_retry_task = proxy._retry_task
            first_retry_scheduled.set()

    proxy.hassette.api.get_states_raw = AsyncMock(side_effect=failing_get_states_raw)
    proxy._schedule_retry = observed_schedule_retry  # pyright: ignore[reportAttributeAccessIssue]

    await proxy.on_initialize()
    await asyncio.wait_for(first_retry_scheduled.wait(), timeout=SYNC_WAIT_TIMEOUT)
    proxy._schedule_retry = original_schedule_retry  # pyright: ignore[reportAttributeAccessIssue]

    first_retry = first_retry_task
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
    # The failed reconnect never reaches _commit_candidate_states (the only place that assigns
    # maintained_generation), and on_disconnect() does not touch it either — so it stays at the
    # generation the fixture's initial bootstrap sync established before this test began.
    assert state_proxy.maintained_generation == 1

    await state_proxy.load_cache()

    assert snapshot_calls == 2
    assert state_proxy.cache_freshness == StateCacheFreshness.FRESH
    assert state_proxy.maintained_generation == 2


async def test_duplicate_reconnect_waiters_do_not_retry_immediately_after_failure(state_proxy: StateProxy) -> None:
    state_proxy.states = {"light.kitchen": make_light_state_dict("light.kitchen", "on")}
    await state_proxy.on_disconnect()
    state_proxy.hassette.websocket_service.get_connected_generation.return_value = 2
    snapshot_entered, release_snapshot, failing_snapshot = gated_get_states_raw_factory(error=RuntimeError("boom"))

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
    # The release event is deliberately never set() — the snapshot call blocks forever, so
    # on_disconnect() must cancel it rather than wait for a result.
    sync_entered, _never_release, blocked_snapshot = gated_get_states_raw_factory(
        result=[make_light_state_dict("light.kitchen", "on")]
    )

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


async def test_shutdown_preserves_initial_state_capability_event_identity() -> None:
    """`on_shutdown` must not rebind `_initial_state_capability_event` to a new object — any
    coroutine already parked in `wait_initial_state_capability(timeout=None)` holds a reference
    to the OLD event's `.wait()` coroutine, which is tied to that specific object. If shutdown
    replaces the attribute with a fresh `asyncio.Event()` instead of calling `.clear()` on the
    existing one, a future `.set()` on the new object (e.g. the next successful initial sync)
    never reaches the orphaned waiter — it hangs forever. `AppBootstrapCoordinator` awaits this
    method with no timeout in production, so this orphaning is a permanent bootstrap hang, not
    just a slow one.
    """
    proxy = build_state_proxy()
    proxy.hassette.api.get_states_raw = AsyncMock(return_value=[])
    await proxy.on_initialize()
    assert await proxy.wait_initial_state_capability(timeout=SYNC_WAIT_TIMEOUT) is True

    # Reset capability to the not-set state so the waiter below actually parks on `.wait()`
    # instead of returning immediately via the `is_set()` fast path.
    proxy._initial_state_capability_event.clear()

    # Deterministic gate: instrument the real event's `.wait()` so we know the waiter task has
    # actually reached the blocking call, instead of racing a scheduler tick with `sleep(0)`.
    entered_wait = asyncio.Event()
    original_wait = proxy._initial_state_capability_event.wait

    async def wait_and_signal() -> bool:
        entered_wait.set()
        return await original_wait()

    proxy._initial_state_capability_event.wait = wait_and_signal  # pyright: ignore[reportAttributeAccessIssue]

    waiter_task = asyncio.create_task(proxy.wait_initial_state_capability(timeout=None))
    await asyncio.wait_for(entered_wait.wait(), timeout=SYNC_WAIT_TIMEOUT)
    assert not waiter_task.done()

    await proxy.on_shutdown()
    assert not waiter_task.done()  # shutdown alone never wakes a waiter; only a later `.set()` can

    # Simulate the next successful initial sync completing after shutdown/restart, which would
    # call `.set()` on whatever object `_initial_state_capability_event` currently references.
    proxy._initial_state_capability_event.set()

    result = await asyncio.wait_for(waiter_task, timeout=SYNC_WAIT_TIMEOUT)
    assert result is True


async def test_state_proxy_starts_with_api_mock_websocket_service_spec(
    test_config: HassetteConfig, unused_tcp_port_factory
) -> None:
    """`with_api_mock()` installs `Mock(spec=WebsocketService)`; `subscribe_to_events()` must be
    able to call `.add()` on `connected_observers`/`disconnected_observers` against that spec'd
    mock without raising `AttributeError`, same as it does against the unspec'd mock the other
    harness paths install.

    ``require_initial_state_capability=False`` skips waiting on the background initial sync —
    ``with_api_mock()`` only mocks the REST layer, not the websocket ``send_and_wait()`` path
    initial sync depends on, so full sync success is out of scope here. This isolates the
    assertion to the specific failure mode reported: the synchronous ``subscribe_to_events()``
    call during resource startup, before sync ever begins.
    """
    harness = HassetteHarness(test_config, unused_tcp_port=unused_tcp_port_factory())
    async with build_harness(
        harness.with_api_mock().with_state_proxy(require_initial_state_capability=False)
    ) as started:
        assert started.state_proxy.state_change_sub is not None
