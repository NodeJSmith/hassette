from hassette import App, AppConfig
from hassette.test_utils import AppTestHarness


class SensorApp(App[AppConfig]):
    async def on_initialize(self):
        # App registers two handlers for the same entity
        self.bus.on_state_change("sensor.temp", handler=self.on_temp_state)
        self.bus.on_attribute_change("sensor.temp", "temperature", handler=self.on_temp_attr)

    async def on_temp_state(self):
        pass

    async def on_temp_attr(self):
        pass


async def test_both_handlers_fire():
    async with AppTestHarness(SensorApp, config={}) as harness:
        # simulate_attribute_change fires BOTH handlers.
        await harness.simulate_attribute_change("sensor.temp", "temperature", old_value=20, new_value=21)

        # Account for this in count assertions
        harness.api_recorder.assert_call_count("call_service", 2)  # not 1
