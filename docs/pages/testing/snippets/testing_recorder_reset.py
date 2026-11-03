from hassette.testing import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_recorder_reset():
    async with AppTestHarness(
        MotionLights,
        config={
            "instance_name": "motion_lights",
            "motion_entity": "binary_sensor.motion",
            "light_entity": "light.hallway",
        },
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.motion", old_value="off", new_value="on"
        )
        harness.api_recorder.reset()  # ignore calls from the above simulate

        await harness.simulate_state_change(
            "binary_sensor.motion", old_value="on", new_value="off"
        )
        await harness.simulate_state_change(
            "binary_sensor.motion", old_value="off", new_value="on"
        )
        # Only the second motion event's call remains
        harness.api_recorder.assert_call_count(
            "turn_on", 1, entity_id="light.hallway"
        )
