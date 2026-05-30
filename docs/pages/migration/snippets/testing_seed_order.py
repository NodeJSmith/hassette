from hassette import App, AppConfig
from hassette.test_utils import AppTestHarness


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change("binary_sensor.motion", handler=self.on_motion, name="motion")

    async def on_motion(self) -> None: ...


async def test_correct_order():
    async with AppTestHarness(MyApp, config={}) as harness:
        # Correct: seed first, simulate second
        await harness.set_state("binary_sensor.motion", "off")
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")

        # Wrong: set_state() after simulate_state_change() overwrites the simulated state
        await harness.simulate_state_change("binary_sensor.motion", old_value="off", new_value="on")
        await harness.set_state("binary_sensor.motion", "off")  # clobbers the simulated state
