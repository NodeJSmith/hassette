from hassette.testing import AppTestHarness

from my_apps.light_app import LightApp


async def test_simulate_attribute_change():
    async with AppTestHarness(
        LightApp, config={"instance_name": "light_app"}
    ) as harness:
        # Seed state first so the event keeps "on" instead of falling back to "unknown"
        await harness.set_state("light.kitchen", "on", brightness=128)
        await harness.simulate_attribute_change(
            "light.kitchen",
            "brightness",
            old_value=128,
            new_value=255,
        )

        # ...or pass state= explicitly for a one-off
        await harness.simulate_attribute_change(
            "light.kitchen",
            "brightness",
            old_value=128,
            new_value=255,
            state="on",
        )
