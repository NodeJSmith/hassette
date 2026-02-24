from unittest.mock import AsyncMock, patch

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.resources.base import Service
from hassette.test_utils import make_service_failed_event, make_service_running_event, preserve_config, wait_for
from hassette.test_utils.reset import reset_hassette_lifecycle
from hassette.types import ResourceStatus, Topic


@pytest.fixture
async def get_service_watcher_mock(hassette_with_bus):
    """Return a fresh service watcher for each test."""
    watcher = ServiceWatcher(hassette_with_bus, parent=hassette_with_bus)
    original_children = list(hassette_with_bus.children)
    with preserve_config(hassette_with_bus.config):
        yield watcher
        # Clean up bus listeners registered by this watcher
        await watcher.on_shutdown()
        await reset_hassette_lifecycle(hassette_with_bus, original_children=original_children)


def get_dummy_service(called: dict[str, int], hassette, *, fail: bool = False) -> Service:
    class _Dummy(Service):
        """Does nothing, just tracks calls."""

        async def serve(self):
            pass

        async def on_shutdown(self):
            called["cancel"] += 1

        async def on_initialize(self):
            called["start"] += 1
            if fail:
                raise RuntimeError("always fails")

    return _Dummy(hassette)


async def test_restart_service_cancels_then_starts(get_service_watcher_mock: ServiceWatcher):
    """Restarting a failed service cancels and reinitializes it."""
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, get_service_watcher_mock.hassette)
    get_service_watcher_mock.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await get_service_watcher_mock.restart_service(event)

    await wait_for(
        lambda: call_counts == {"cancel": 1, "start": 1},
        desc="restart_service completed",
    )

    assert call_counts == {"cancel": 1, "start": 1}, (
        f"Expected cancel and start to be called once each, got {call_counts}"
    )


async def test_always_failing_service_stops_after_max_attempts(get_service_watcher_mock: ServiceWatcher):
    """A service that always fails on restart stops being restarted after max attempts."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    hassette.config.service_restart_max_attempts = 3
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, hassette, fail=True)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Each call to restart_service raises because the dummy always fails,
    # which increments the attempt counter.
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        for _ in range(3):
            with pytest.raises(RuntimeError, match="always fails"):
                await watcher.restart_service(event)

    assert watcher._restart_attempts[key] == 3
    assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before max attempts exceeded"

    # The 4th call should trigger shutdown (max attempts exceeded)
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await watcher.restart_service(event)

    assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after max attempts exceeded"
    # Attempt counter stays at 3 (not incremented because we returned early)
    assert watcher._restart_attempts[key] == 3
    # on_initialize was called 3 times (each restart attempted the init)
    assert call_counts["start"] == 3


async def test_max_restart_exceeded_emits_crashed_event(get_service_watcher_mock: ServiceWatcher):
    """When max restart attempts are exceeded, a CRASHED event is emitted before shutdown."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    hassette.config.service_restart_max_attempts = 1
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, hassette, fail=True)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    # First call fails and increments counter
    with (
        patch("hassette.core.service_watcher.asyncio.sleep", return_value=None),
        pytest.raises(RuntimeError, match="always fails"),
    ):
        await watcher.restart_service(event)

    # Second call exceeds max — should emit CRASHED then shutdown
    mock_send = AsyncMock()
    original_send = hassette.send_event
    hassette.send_event = mock_send  # type: ignore[assignment]
    try:
        with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
            await watcher.restart_service(event)
    finally:
        hassette.send_event = original_send  # type: ignore[assignment]

    # First send_event call should be the CRASHED event (shutdown may emit STOPPED after)
    assert mock_send.call_count >= 1
    first_call = mock_send.call_args_list[0]
    assert first_call[0][0] == Topic.HASSETTE_EVENT_SERVICE_STATUS
    crashed_event = first_call[0][1]
    assert crashed_event.payload.data.status == ResourceStatus.CRASHED
    assert crashed_event.payload.data.previous_status == ResourceStatus.FAILED
    assert crashed_event.payload.data.resource_name == dummy_service.class_name


async def test_exponential_backoff_applied(get_service_watcher_mock: ServiceWatcher):
    """Backoff delay increases exponentially between restart attempts."""
    watcher = get_service_watcher_mock
    watcher.hassette.config.service_restart_max_attempts = 5
    watcher.hassette.config.service_restart_backoff_seconds = 1.0
    watcher.hassette.config.service_restart_backoff_multiplier = 2.0
    watcher.hassette.config.service_restart_max_backoff_seconds = 60.0

    call_counts = {"cancel": 0, "start": 0}
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    sleep_calls: list[float] = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)

    with patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep):
        for _ in range(3):
            with pytest.raises(RuntimeError, match="always fails"):
                await watcher.restart_service(event)

    # attempt 0: backoff = 1.0 * 2^0 = 1.0
    # attempt 1: backoff = 1.0 * 2^1 = 2.0
    # attempt 2: backoff = 1.0 * 2^2 = 4.0
    assert sleep_calls == [1.0, 2.0, 4.0]


async def test_config_values_are_respected(get_service_watcher_mock: ServiceWatcher):
    """Custom config values for max attempts and backoff are respected."""
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    hassette.config.service_restart_max_attempts = 1
    hassette.config.service_restart_backoff_seconds = 0.5
    hassette.config.service_restart_backoff_multiplier = 3.0
    hassette.config.service_restart_max_backoff_seconds = 10.0

    call_counts = {"cancel": 0, "start": 0}
    dummy_service = get_dummy_service(call_counts, hassette, fail=True)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    # First attempt: should use backoff of 0.5 * 3^0 = 0.5
    with (
        patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep),
        pytest.raises(RuntimeError, match="always fails"),
    ):
        await watcher.restart_service(event)

    assert sleep_calls == [0.5]
    assert watcher._restart_attempts[key] == 1
    assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before max attempts exceeded"

    # Second attempt: max_attempts=1, so should trigger shutdown
    with patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep):
        await watcher.restart_service(event)

    assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after max attempts exceeded"
    # No additional sleep call — we returned early
    assert sleep_calls == [0.5]
    assert call_counts["start"] == 1  # only the first attempt called on_initialize


async def test_attempt_counter_increments_when_restart_succeeds_but_serve_fails_later(
    get_service_watcher_mock: ServiceWatcher,
):
    """Counter must increment even when restart() itself doesn't raise.

    Regression test: serve() runs asynchronously, so restart() returns before
    serve() has a chance to fail. If the counter is cleared on "success",
    every FAILED event restarts from attempt 1 and the service never gives up.
    """
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    hassette.config.service_restart_max_attempts = 3

    call_counts = {"cancel": 0, "start": 0}
    # fail=False: on_initialize succeeds, restart() won't raise
    dummy_service = get_dummy_service(call_counts, hassette, fail=False)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Simulate 3 FAILED events arriving (serve() failing async each time).
    # restart() succeeds each time because on_initialize doesn't raise.
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        for i in range(3):
            await watcher.restart_service(event)
            assert watcher._restart_attempts[key] == i + 1, (
                f"After restart {i + 1}, counter should be {i + 1} but got {watcher._restart_attempts[key]}"
            )

    assert not hassette.shutdown_event.is_set(), "Shutdown should not happen before max attempts exceeded"

    # 4th FAILED event: counter is 3, max is 3 → should trigger shutdown
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await watcher.restart_service(event)

    assert hassette.shutdown_event.is_set(), "Shutdown should be triggered after max attempts exceeded"
    # Counter stays at 3, start was only called 3 times (not 4)
    assert watcher._restart_attempts[key] == 3
    assert call_counts["start"] == 3


async def test_max_backoff_caps_delay(get_service_watcher_mock: ServiceWatcher):
    """Backoff delay is capped by service_restart_max_backoff_seconds."""
    watcher = get_service_watcher_mock
    watcher.hassette.config.service_restart_max_attempts = 10
    watcher.hassette.config.service_restart_backoff_seconds = 10.0
    watcher.hassette.config.service_restart_backoff_multiplier = 10.0
    watcher.hassette.config.service_restart_max_backoff_seconds = 30.0

    call_counts = {"cancel": 0, "start": 0}
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    sleep_calls: list[float] = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)

    with patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep):
        for _ in range(3):
            with pytest.raises(RuntimeError, match="always fails"):
                await watcher.restart_service(event)

    # attempt 0: min(10 * 10^0, 30) = 10.0
    # attempt 1: min(10 * 10^1, 30) = 30.0 (capped)
    # attempt 2: min(10 * 10^2, 30) = 30.0 (capped)
    assert sleep_calls == [10.0, 30.0, 30.0]


async def test_restart_counter_resets_on_service_running(get_service_watcher_mock: ServiceWatcher):
    """Restart attempt counter resets when a service transitions to RUNNING."""
    watcher = get_service_watcher_mock
    watcher.hassette.config.service_restart_max_attempts = 3

    call_counts = {"cancel": 0, "start": 0}
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True)
    watcher.hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Accumulate 2 restart attempts
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        for _ in range(2):
            with pytest.raises(RuntimeError, match="always fails"):
                await watcher.restart_service(event)

    assert watcher._restart_attempts[key] == 2

    # Fire a RUNNING event — counter should reset
    await watcher._on_service_running(make_service_running_event(dummy_service))

    assert key not in watcher._restart_attempts

    # After reset, the service gets a fresh retry budget
    with (
        patch("hassette.core.service_watcher.asyncio.sleep", return_value=None),
        pytest.raises(RuntimeError, match="always fails"),
    ):
        await watcher.restart_service(event)

    assert watcher._restart_attempts[key] == 1  # fresh counter, not 3


async def test_bus_driven_failed_events_trigger_shutdown_after_max_attempts(
    get_service_watcher_mock: ServiceWatcher,
):
    """Full wiring: bus dispatch -> listener -> restart_service -> hassette.shutdown().

    Unlike other tests that call restart_service() directly, this one fires
    a single FAILED event through the bus.  Because the dummy service always
    fails on restart, handle_failed() emits a new FAILED event each time,
    creating a cascade that exhausts the retry budget and triggers shutdown.
    """
    watcher = get_service_watcher_mock
    hassette = watcher.hassette
    hassette.config.service_restart_max_attempts = 2
    # Zero backoff so asyncio.sleep is never called by the handler.
    # Patching asyncio.sleep globally would prevent wait_for() from yielding
    # to the event loop, starving the bus dispatch tasks.
    hassette.config.service_restart_backoff_seconds = 0.0

    call_counts = {"cancel": 0, "start": 0}
    # fail=True: on_initialize raises → handle_failed emits a new FAILED event,
    # creating the cascade that eventually exceeds the retry budget.
    dummy_service = get_dummy_service(call_counts, hassette, fail=True)
    hassette.children.append(dummy_service)

    event = make_service_failed_event(dummy_service)

    # Stub hassette.shutdown() to set the event without running the full
    # lifecycle (which would cancel_all tasks including this test's coroutine).
    async def _shutdown_stub() -> None:
        hassette.shutdown_event.set()

    hassette.shutdown = _shutdown_stub  # type: ignore[assignment]

    # Initialize watcher to register bus listeners, then await get_listeners()
    # which guarantees all preceding add_listener tasks have completed
    await watcher.on_initialize()
    listeners = await watcher.bus.get_listeners()
    assert len(listeners) == 4, f"Expected 4 listeners, got {len(listeners)}"

    # Single FAILED event kicks off the cascade:
    #   FAILED → restart_service (counter 0→1) → service.restart() fails
    #   → handle_failed sends FAILED → restart_service (counter 1→2 ≥ max)
    #   → hassette.shutdown()
    await hassette.send_event(event.topic, event)
    await wait_for(
        lambda: hassette.shutdown_event.is_set(),
        desc="shutdown triggered after max attempts exceeded",
    )
