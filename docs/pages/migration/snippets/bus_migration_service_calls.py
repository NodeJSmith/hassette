from hassette import App


class MyApp(App):
    async def on_initialize(self):
        await self.bus.on_call_service(
            domain="light",
            service="turn_on",
            handler=self.on_service,
            name="light_turn_on",
        )

    async def on_service(self):
        self.logger.info("Light turned on")
