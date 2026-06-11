from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_light_turns_on_when_motion_detected():
    # --8<-- [start:harness_setup]
    async with AppTestHarness(
        MotionLights,
        config={"motion_entity": "binary_sensor.hallway", "light_entity": "light.hallway"},
    ) as harness:
        # --8<-- [end:harness_setup]
        # --8<-- [start:simulate]
        await harness.simulate_state_change("binary_sensor.hallway", old_value="off", new_value="on")
        # --8<-- [end:simulate]
        # --8<-- [start:assert_called]
        harness.api_recorder.assert_called(
            "turn_on",
            entity_id="light.hallway",
        )
        # --8<-- [end:assert_called]
