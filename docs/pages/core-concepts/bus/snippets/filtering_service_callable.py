from hassette import App


class LightApp(App):
    async def on_initialize(self):
        # Callable values: custom check
        await self.bus.on_call_service(
            domain="light",
            service="turn_on",
            where={"brightness": lambda v: isinstance(v, int) and v > 200},
            handler=self.on_bright_lights,
            name="bright_lights",
        )

    async def on_bright_lights(self, event):
        pass
