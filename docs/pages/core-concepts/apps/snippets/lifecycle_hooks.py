from hassette import App


class MyApp(App):
    async def on_initialize(self):
        self.logger.info("App starting up!")
        await self.bus.on_state_change("sensor.power", handler=self.on_power, name="power_sensor")

    async def on_power(self, event):
        pass
