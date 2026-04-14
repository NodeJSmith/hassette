from whenever import Instant

from hassette import App, AppConfig, D, states
from hassette.test_utils import AppTestHarness


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


async def test_motion_turns_on_light():
    async with AppTestHarness(MotionLightApp, config={"light_entity": "light.kitchen"}) as harness:
        await harness.set_state("binary_sensor.motion", "off")
        await harness.set_state("light.kitchen", "off", brightness=0)

        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")
