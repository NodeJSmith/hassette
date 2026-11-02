"""Presence helpers used as a bus ``where=`` filter, as documented on the bus filtering page.

Each case builds a fresh harness: a second ``set_state`` for the same entity reads stale until #1517 is fixed.
"""

import pytest

from hassette.app.app import App
from hassette.app.app_config import AppConfig
from hassette.testing import AppTestHarness


class DoorConfig(AppConfig):
    """Minimal config for the presence-filtered app."""


class DoorApp(App[DoorConfig]):
    """Counts front door events that pass a ``nobody_home()`` filter."""

    fired: int

    async def on_initialize(self) -> None:
        self.fired = 0
        await self.bus.on_state_change(
            "binary_sensor.front_door",
            handler=self.on_door,
            where=lambda _: self.states.nobody_home(),
            name="door_when_empty",
        )

    async def on_door(self) -> None:
        self.fired += 1


@pytest.mark.parametrize(
    ("presence", "expected_fired"),
    [
        pytest.param({}, 1, id="no_tracked_entities"),
        pytest.param({"person.jessica": "home"}, 0, id="someone_home"),
        pytest.param({"person.jessica": "not_home", "person.tierra": "Work"}, 1, id="everyone_away"),
    ],
)
async def test_nobody_home_gates_handler(presence: dict[str, str | tuple[str, dict]], expected_fired: int) -> None:
    """The filter reads presence at dispatch: the states are seeded after on_initialize registers the listener."""
    async with AppTestHarness(DoorApp, config={"instance_name": "door"}) as harness:
        await harness.set_states(presence)

        await harness.simulate_state_change("binary_sensor.front_door", old_value="off", new_value="on")

        assert harness.app.fired == expected_fired
