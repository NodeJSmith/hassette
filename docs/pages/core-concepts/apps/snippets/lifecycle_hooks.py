from hassette import App


class MyApp(App):
    async def on_initialize(self):
        self.logger.info("App starting up!")
        self.bus.on_state_change("sensor.power", handler=self.on_power)

    async def on_power(self, event):
        pass
