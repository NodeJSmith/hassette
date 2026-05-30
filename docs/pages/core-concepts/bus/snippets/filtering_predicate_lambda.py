from hassette import App, C


class TempApp(App):
    async def on_initialize(self):
        await self.bus.on_state_change("sensor.temperature", handler=self.on_temp_change, changed_to=C.Comparison("gt", 25), name="temp_high")

    async def on_temp_change(self, event):
        pass
