from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_light_turns_on_when_motion_detected():
    async with AppTestHarness(
        MotionLights,
        config={"motion_entity": "binary_sensor.hallway", "light_entity": "light.hallway"},
    ) as harness:
        await harness.simulate_state_change(
            "binary_sensor.hallway", old_value="off", new_value="on"
        )
        harness.api_recorder.assert_called(
            "turn_on",
            entity_id="light.hallway",
        )
