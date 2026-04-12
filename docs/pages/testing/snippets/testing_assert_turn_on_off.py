from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_turn_on_off_recording():
    async with AppTestHarness(MotionLights, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        # Your app calls: await self.api.turn_on("light.kitchen", domain="light")
        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen", domain="light")

        # Your app calls: await self.api.turn_off("light.kitchen", domain="light")
        harness.api_recorder.assert_called("turn_off", entity_id="light.kitchen", domain="light")
