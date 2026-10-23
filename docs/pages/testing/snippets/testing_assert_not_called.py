from hassette.testing import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_not_called():
    async with AppTestHarness(
        MotionLights,
        config={
            "instance_name": "motion_lights",
            "motion_entity": "binary_sensor.motion",
            "light_entity": "light.kitchen",
        },
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.motion", old_value="off", new_value="on"
        )

        # The off handler needs 120 seconds of "off", so nothing turned the light off
        harness.api_recorder.assert_not_called("turn_off")
