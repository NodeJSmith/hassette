from hassette.test_utils import AppTestHarness

from my_apps.light_app import LightApp


async def test_simulate_attribute_change():
    async with AppTestHarness(LightApp, config={}) as harness:
        await harness.simulate_attribute_change(
            "light.kitchen",
            "brightness",
            old_value=128,
            new_value=255,
        )

        # Seed state first to avoid the "unknown" fallback in predicates
        await harness.set_state("light.kitchen", "on", brightness=128)
        # ...or pass state= explicitly for a one-off:
        await harness.simulate_attribute_change(
            "light.kitchen",
            "brightness",
            old_value=128,
            new_value=255,
            state="on",  # avoids the "unknown" fallback
        )
