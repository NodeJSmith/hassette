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

DURATION = 0.05  # 50 ms — fast enough for tests


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
