from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_call_count():
    async with AppTestHarness(MotionLights, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")
        harness.api_recorder.assert_call_count("call_service", 2)
