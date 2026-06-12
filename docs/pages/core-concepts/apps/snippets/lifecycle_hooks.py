from hassette import App, D
from hassette.models import states


class MyApp(App):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change("sensor.power", handler=self.on_power, name="power_sensor")
        await self.scheduler.run_in(self.check_status, 30, name="startup_check")

    async def on_power(self, new_state: D.StateNew[states.SensorState]) -> None:
        pass

    async def check_status(self) -> None:
        pass
