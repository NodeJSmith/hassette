from hassette import App, AppConfig
from hassette.test_utils import AppTestHarness


class SensorApp(App[AppConfig]):
    async def on_initialize(self):
        # on_state_change with changed=False fires even when only attributes change
        self.bus.on_state_change("sensor.temp", changed=False, handler=self.on_temp_state)
        self.bus.on_attribute_change("sensor.temp", "temperature", handler=self.on_temp_attr)

    async def on_temp_state(self):
        await self.api.turn_on("light.indicator")

    async def on_temp_attr(self):
        await self.api.turn_on("light.indicator")


async def test_both_handlers_fire():
    async with AppTestHarness(SensorApp, config={}) as harness:
        # simulate_attribute_change fires BOTH handlers because on_state_change
        # was registered with changed=False (fires for any state_changed event).
        # With the default changed=True, only the attribute handler would fire.
        await harness.simulate_attribute_change("sensor.temp", "temperature", old_value=20, new_value=21)

        # Both handlers ran
        harness.api_recorder.assert_call_count("turn_on", 2)
