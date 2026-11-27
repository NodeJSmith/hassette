"""System tests for HelperClient — real HA interactions through a running Hassette instance."""

from typing import Any

import pytest

from hassette import Hassette
from hassette.api.helpers import HelperDomain
from hassette.models.helpers import (
    CreateCounterParams,
    CreateInputBooleanParams,
    CreateInputButtonParams,
    CreateInputDatetimeParams,
    CreateInputNumberParams,
    CreateInputSelectParams,
    CreateInputTextParams,
    CreateTimerParams,
    UpdateCounterParams,
    UpdateInputBooleanParams,
    UpdateInputButtonParams,
    UpdateInputDatetimeParams,
    UpdateInputNumberParams,
    UpdateInputSelectParams,
    UpdateInputTextParams,
    UpdateTimerParams,
)
from hassette.testing import wait_for

from .conftest import make_system_config, startup_context

pytestmark = [pytest.mark.system]

# HA registers the entity and applies counter actions asynchronously after acking the WS
# command, so every read below polls rather than asserting on a single fetch.
STATE_TIMEOUT_SECONDS = 10.0

# One minimal valid create per helper domain, plus a rename. Each case runs HA's real
# create/list/update/delete WS commands, so a required field HA stops sending (or a type it
# changes) fails Record validation here and in the HA dev canary, before it reaches an app.
HELPER_CRUD_CASES = [
    pytest.param(
        "input_boolean",
        CreateInputBooleanParams(name="CRUD Probe Boolean", initial=True),
        UpdateInputBooleanParams(name="CRUD Probe Boolean Renamed"),
        id="input_boolean",
    ),
    pytest.param(
        "input_button",
        CreateInputButtonParams(name="CRUD Probe Button"),
        UpdateInputButtonParams(name="CRUD Probe Button Renamed"),
        id="input_button",
    ),
    pytest.param(
        "input_datetime",
        CreateInputDatetimeParams(name="CRUD Probe Datetime", has_date=True, has_time=True),
        UpdateInputDatetimeParams(name="CRUD Probe Datetime Renamed"),
        id="input_datetime",
    ),
    pytest.param(
        "input_number",
        CreateInputNumberParams(name="CRUD Probe Number", min=0, max=10, step=0.5),
        UpdateInputNumberParams(name="CRUD Probe Number Renamed"),
        id="input_number",
    ),
    pytest.param(
        "input_select",
        CreateInputSelectParams(name="CRUD Probe Select", options=["a", "b"]),
        UpdateInputSelectParams(name="CRUD Probe Select Renamed"),
        id="input_select",
    ),
    pytest.param(
        "input_text",
        CreateInputTextParams(name="CRUD Probe Text", min=0, max=50),
        UpdateInputTextParams(name="CRUD Probe Text Renamed"),
        id="input_text",
    ),
    pytest.param(
        "counter",
        CreateCounterParams(name="CRUD Probe Counter", initial=3, step=2),
        UpdateCounterParams(name="CRUD Probe Counter Renamed"),
        id="counter",
    ),
    pytest.param(
        "timer",
        CreateTimerParams(name="CRUD Probe Timer", duration="00:01:00"),
        UpdateTimerParams(name="CRUD Probe Timer Renamed"),
        id="timer",
    ),
]


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


@pytest.mark.parametrize(("domain", "create_params", "update_params"), HELPER_CRUD_CASES)
async def test_helper_crud_against_real_ha(
    ha_container: str, tmp_path, domain: HelperDomain, create_params: Any, update_params: Any
) -> None:
    """create/list/update/delete round-trip one helper per domain and parse HA's real records."""
    config = make_system_config(ha_container, tmp_path)
    async with startup_context(config) as hassette:
        helpers = hassette.api.helpers
        created = await helpers.create(create_params)
        try:
            assert created.name == create_params.name

            # list() also returns any other stored helpers in the domain, so match on the new id.
            listed = {record.id: record for record in await helpers.list(domain)}
            assert listed.get(created.id) == created

            # HA replaces the stored item on update, so this also proves the fields the rename
            # didn't mention survive it.
            updated = await helpers.update(created.id, update_params)
            assert updated.name == update_params.name
            assert updated.model_dump(exclude={"name"}) == created.model_dump(exclude={"name"})

            listed = {record.id: record for record in await helpers.list(domain)}
            assert listed.get(created.id) == updated
        finally:
            await helpers.delete(domain, created.id)

        assert created.id not in {record.id for record in await helpers.list(domain)}
