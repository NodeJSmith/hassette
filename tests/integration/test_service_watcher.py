import asyncio
from unittest.mock import patch

import pytest

from hassette.core.service_watcher import ServiceWatcher
from hassette.events.hassette import HassetteServiceEvent
from hassette.resources.base import Service
from hassette.test_utils import preserve_config
from hassette.types.enums import ResourceStatus


@pytest.fixture
def get_service_watcher_mock(hassette_with_bus):
    """Return a fresh service watcher for each test."""
    watcher = ServiceWatcher.create(hassette_with_bus)
    original_children = list(hassette_with_bus.children)
    with preserve_config(hassette_with_bus.config):
        yield watcher
        hassette_with_bus.children[:] = original_children


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


def _make_failed_event(service: Service) -> HassetteServiceEvent:
    return HassetteServiceEvent.from_data(
        resource_name=service.class_name,
        role=service.role,
        status=ResourceStatus.FAILED,
        exception=Exception("test"),
    )


async def test_restart_service_cancels_then_starts(get_service_watcher_mock: ServiceWatcher):
    """Restarting a failed service cancels and reinitializes it."""
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, get_service_watcher_mock.hassette)
    get_service_watcher_mock.hassette.children.append(dummy_service)

    event = _make_failed_event(dummy_service)

    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await get_service_watcher_mock.restart_service(event)

    await asyncio.sleep(0.1)  # allow restart to run

    assert call_counts == {"cancel": 1, "start": 1}, (
        f"Expected cancel and start to be called once each, got {call_counts}"
    )


async def test_always_failing_service_stops_after_max_attempts(get_service_watcher_mock: ServiceWatcher):
    """A service that always fails on restart stops being restarted after max attempts."""
    watcher = get_service_watcher_mock
    watcher.hassette.config.service_restart_max_attempts = 3
    call_counts = {"cancel": 0, "start": 0}

    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True)
    watcher.hassette.children.append(dummy_service)

    event = _make_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Each call to restart_service raises because the dummy always fails,
    # which increments the attempt counter.
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        for _ in range(3):
            with pytest.raises(RuntimeError, match="always fails"):
                await watcher.restart_service(event)

    assert watcher._restart_attempts[key] == 3

    # The 4th call should be a no-op (max attempts exceeded)
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await watcher.restart_service(event)

    # Attempt counter stays at 3 (not incremented because we returned early)
    assert watcher._restart_attempts[key] == 3
    # on_initialize was called 3 times (each restart attempted the init)
    assert call_counts["start"] == 3


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

    event = _make_failed_event(dummy_service)

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
    watcher.hassette.config.service_restart_max_attempts = 1
    watcher.hassette.config.service_restart_backoff_seconds = 0.5
    watcher.hassette.config.service_restart_backoff_multiplier = 3.0
    watcher.hassette.config.service_restart_max_backoff_seconds = 10.0

    call_counts = {"cancel": 0, "start": 0}
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=True)
    watcher.hassette.children.append(dummy_service)

    event = _make_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    sleep_calls: list[float] = []

    async def mock_sleep(delay):
        sleep_calls.append(delay)

    # First attempt: should use backoff of 0.5 * 3^0 = 0.5
    with (
        patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep),
        pytest.raises(RuntimeError, match="always fails"),
    ):
        await watcher.restart_service(event)

    assert sleep_calls == [0.5]
    assert watcher._restart_attempts[key] == 1

    # Second attempt: max_attempts=1, so should be rejected
    with patch("hassette.core.service_watcher.asyncio.sleep", side_effect=mock_sleep):
        await watcher.restart_service(event)

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
    watcher.hassette.config.service_restart_max_attempts = 3

    call_counts = {"cancel": 0, "start": 0}
    # fail=False: on_initialize succeeds, restart() won't raise
    dummy_service = get_dummy_service(call_counts, watcher.hassette, fail=False)
    watcher.hassette.children.append(dummy_service)

    event = _make_failed_event(dummy_service)
    key = watcher._service_key(dummy_service.class_name, dummy_service.role)

    # Simulate 3 FAILED events arriving (serve() failing async each time).
    # restart() succeeds each time because on_initialize doesn't raise.
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        for i in range(3):
            await watcher.restart_service(event)
            assert watcher._restart_attempts[key] == i + 1, (
                f"After restart {i + 1}, counter should be {i + 1} but got {watcher._restart_attempts[key]}"
            )

    # 4th FAILED event: counter is 3, max is 3 → should refuse to restart
    with patch("hassette.core.service_watcher.asyncio.sleep", return_value=None):
        await watcher.restart_service(event)

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

    event = _make_failed_event(dummy_service)

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
