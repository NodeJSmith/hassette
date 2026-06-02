from hassette import App


class MyApp(App):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change("sensor.power", handler=self.on_power, name="power_sensor")
        await self.scheduler.run_in(self.check_status, 30, name="startup_check")

    async def on_power(self, event) -> None:
        pass

    async def check_status(self) -> None:
        pass
