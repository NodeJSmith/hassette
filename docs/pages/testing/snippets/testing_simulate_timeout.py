from hassette.test_utils import AppTestHarness

from my_apps.slow_app import SlowApp


async def test_with_custom_timeout():
    async with AppTestHarness(SlowApp, config={}) as harness:
        await harness.simulate_state_change(
            "sensor.slow_device",
            old_value="off",
            new_value="on",
            timeout=5.0,
        )
