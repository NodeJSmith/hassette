"""Shared fixtures for bus integration tests."""

import typing
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from hassette.resources.lifecycle import mark_ready
from hassette.test_utils.harness import HassetteHarness

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.bus import Bus

DURATION = 0.2  # 200 ms — wide enough for CI scheduling jitter
ASYNC_SAFETY_TIMEOUT = 2.0  # safety ceiling awaiting an async completion signal (timer, immediate-fire, error handler)
PARTIAL_HOLD = DURATION * 0.3  # brief wait before a mid-cycle action (cancel, attribute refresh)
NEAR_HALF_HOLD = DURATION * 0.4  # roughly half the duration — simulates a timer partway through its cycle
REGISTRATION_SETTLE_DELAY = 0.05  # let listener registration complete before inspecting router state
CANCEL_SETTLE_DELAY = 0.02  # let cancellation-listener add/remove settle before inspecting router state

# Shared by the immediate+duration "elapsed boundary" test pairs in test_bus_immediate.py and
# test_bus_error_handler_combos.py — each pair seeds a last_changed offset on one side of the
# elapsed>=duration boundary and shares the same duration value.
ELAPSED_BOUNDARY_DURATION = 5.0  # duration used across every elapsed-boundary test pair
ELAPSED_EXCEEDS_OFFSET_SECONDS = 10  # last_changed offset landing on the "elapsed >= duration" side
ELAPSED_REMAINING_OFFSET_SECONDS = 3  # last_changed offset landing on the "elapsed < duration" side
REMAINING_FIRE_TIMEOUT = 4.0  # wait for the timer to fire after the remaining ~2s, plus margin


@pytest.fixture
async def bus_harness(test_config) -> AsyncIterator[tuple[HassetteHarness, "Hassette", "Bus"]]:
    """Fresh harness with bus + state_proxy for bus integration tests.

    Marks the state proxy ready. State is seeded via harness.seed_state().
    The api mock returns an empty state list so load_cache succeeds without HTTP.
    """
    harness = HassetteHarness(test_config, skip_global_set=False)
    harness.with_bus().with_scheduler().with_state_proxy().with_state_registry()

    api_mock = AsyncMock()
    api_mock.sync = AsyncMock()
    api_mock.get_states_raw = AsyncMock(return_value=[])
    harness.hassette._api = api_mock

    await harness.start()

    mark_ready(harness.state_proxy, reason="bus_harness: mark ready for test")

    hassette = typing.cast("Hassette", harness.hassette)
    bus = harness.bus

    try:
        yield harness, hassette, bus
    finally:
        await harness.stop()
