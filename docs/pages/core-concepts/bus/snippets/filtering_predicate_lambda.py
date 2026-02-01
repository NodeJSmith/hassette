from hassette import App, C


class TempApp(App):
    async def on_initialize(self):
        self.bus.on_state_change("sensor.temperature", handler=self.on_temp_change, changed_to=C.Comparison("gt", 25))

    async def on_temp_change(self, event):
        pass
