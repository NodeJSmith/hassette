from hassette import App


class MyApp(App):
    async def my_callback(self):
        await self.api.set_state("sensor.custom", state=42, attributes={"unit": "widgets"})
