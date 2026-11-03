from hassette.testing import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_turn_on_recording():
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

        # Your app calls: await self.api.turn_on("light.kitchen")
        harness.api_recorder.assert_called("turn_on", entity_id="light.kitchen")

        # turn_on records under its own name, so call_service stays empty
        harness.api_recorder.assert_not_called("call_service")
