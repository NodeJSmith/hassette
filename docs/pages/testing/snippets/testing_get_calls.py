from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_get_calls():
    async with AppTestHarness(MotionLights, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        calls = harness.api_recorder.get_calls("call_service")
        for call in calls:
            print(call.kwargs)  # e.g. {"domain": "light", "service": "turn_on", ...}
