from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_recorder_reset():
    async with AppTestHarness(MotionLights, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")
        harness.api_recorder.reset()  # ignore calls from the above simulate

        await harness.simulate_state_change("binary_sensor.motion", old_value="on", new_value="off")
        harness.api_recorder.assert_called("turn_off", entity_id="light.hallway", domain="light")
