from hassette.testing import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_called_examples():
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

        # Assert turn_on was called for a specific entity
        harness.api_recorder.assert_called(
            "turn_on",
            entity_id="light.kitchen",
            domain="light",
        )
