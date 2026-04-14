from hassette.test_utils import AppTestHarness

from my_apps.motion_lights import MotionLights


async def test_assert_called_examples():
    async with AppTestHarness(MotionLights, config={}) as harness:
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        # Assert turn_on was called for a specific entity
        harness.api_recorder.assert_called(
            "turn_on",
            entity_id="light.kitchen",
            domain="light",
        )

        # Assert fire_event was called with a specific event type
        harness.api_recorder.assert_called("fire_event", event_type="my_custom_event")

        # Assert call_service was called directly (for services without a named wrapper)
        harness.api_recorder.assert_called(
            "call_service",
            domain="light",
            service="set_color_temp",
            target={"entity_id": "light.kitchen"},
        )
