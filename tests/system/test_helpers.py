"""System tests for HelperClient — real HA interactions through a running Hassette instance."""

import pytest

from hassette import Hassette
from hassette.models.helpers import CreateCounterParams
from hassette.testing import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]

# HA registers the entity and applies counter actions asynchronously after acking the WS
# command, so every read below polls rather than asserting on a single fetch.
STATE_TIMEOUT_SECONDS = 10.0


async def wait_for_counter_value(hassette: Hassette, entity_id: str, expected: int) -> None:
    """Poll ``entity_id`` until its live value equals ``expected``."""

    async def matches() -> bool:
        state = await hassette.api.get_state_or_none(entity_id)
        return state is not None and state.value == expected

    await wait_for(matches, timeout=STATE_TIMEOUT_SECONDS, desc=f"{entity_id} to reach {expected}")


async def test_counter_shortcuts_against_real_ha(ha_container: str, tmp_path) -> None:
    """increment/decrement/reset succeed against real HA and move the counter's live value.

    Regression test for #1851: HA declares counter.increment/decrement/reset as returning no
    response, so the shortcuts' original ``return_response=True`` payload was rejected outright
    with a service_validation_error. Nothing below the WebSocket boundary is mocked here, so
    this exercises the HA-side contract the unit and integration tests cannot see.
    """
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        record = await hassette.api.helpers.create(CreateCounterParams(name="Counter 1851 Probe", initial=0))
        entity_id = f"counter.{record.id}"
        try:
            await wait_for_counter_value(hassette, entity_id, 0)

            await hassette.api.helpers.increment(entity_id)
            await hassette.api.helpers.increment(entity_id)
            await wait_for_counter_value(hassette, entity_id, 2)

            await hassette.api.helpers.decrement(entity_id)
            await wait_for_counter_value(hassette, entity_id, 1)

            await hassette.api.helpers.reset(entity_id)
            await wait_for_counter_value(hassette, entity_id, 0)
        finally:
            await hassette.api.helpers.delete("counter", record.id)
