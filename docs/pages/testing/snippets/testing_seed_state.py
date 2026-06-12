from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_seed_then_simulate():
    async with AppTestHarness(
        MotionLights,
        config={"motion_entity": "binary_sensor.hallway", "light_entity": "light.hallway"},
    ) as harness:
        # --8<-- [start:seed]
        await harness.set_state("binary_sensor.hallway", "off")
        await harness.simulate_state_change("binary_sensor.hallway", old_value="off", new_value="on")
        # --8<-- [end:seed]
        harness.api_recorder.assert_called("turn_on", entity_id="light.hallway")
