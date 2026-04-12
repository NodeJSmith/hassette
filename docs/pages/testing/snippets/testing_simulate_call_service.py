from hassette.test_utils import AppTestHarness

from my_apps.light_app import LightApp


async def test_simulate_call_service():
    async with AppTestHarness(LightApp, config={}) as harness:
        await harness.simulate_call_service(
            "light",
            "turn_on",
            entity_id="light.kitchen",
            brightness=200,
        )
