import pytest

from hassette import App, AppConfig, D, states
from hassette.test_utils import AppTestHarness, create_state_change_event, make_light_state_dict


class MyConfig(AppConfig):
    light_entity: str = "light.kitchen"


class MotionLightApp(App[MyConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(
            "binary_sensor.motion",
            handler=self.on_motion,
            changed_to="on",
        )

    async def on_motion(self, new_state: D.StateNew[states.BinarySensorState]):
        await self.api.turn_on(self.app_config.light_entity)


@pytest.mark.asyncio
async def test_motion_turns_on_light():
    async with AppTestHarness(MotionLightApp, config={"light_entity": "light.kitchen"}) as harness:
        harness.set_state("binary_sensor.motion", "off")
        harness.set_state("light.kitchen", "off", make_light_state_dict(brightness=0))

        await harness.simulate_state_change(
            create_state_change_event("binary_sensor.motion", old="off", new="on")
        )

        harness.api_recorder.assert_called(
            "turn_on", target={"entity_id": "light.kitchen"}
        )
