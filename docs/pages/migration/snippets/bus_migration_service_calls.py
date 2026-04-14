from hassette import App


class MyApp(App):
    async def on_initialize(self):
        self.bus.on_call_service(
            domain="light",
            service="turn_on",
            handler=self.on_service,
        )

    async def on_service(self):
        self.logger.info("Light turned on")
