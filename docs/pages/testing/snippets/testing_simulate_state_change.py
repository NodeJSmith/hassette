from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_simulate_state_changes():
    async with AppTestHarness(MotionLights, config={}) as harness:
        # Basic state change
        await harness.simulate_state_change(
            "binary_sensor.motion",
            old_value="off",
            new_value="on",
        )

        # With attributes
        await harness.simulate_state_change(
            "sensor.temperature",
            old_value="20.0",
            new_value="21.5",
            old_attrs={"unit_of_measurement": "°C"},
            new_attrs={"unit_of_measurement": "°C"},
        )
