from hassette import App


class CustomEventApp(App):
    async def on_initialize(self):
        # Subscribe to a custom internal event
        self.bus.on("my_custom_event", handler=self.on_custom_event)

        # Subscribe to specific raw HA event
        self.bus.on("hass.event.call_service", handler=self.on_any_service)

    async def on_custom_event(self, event):
        pass

    async def on_any_service(self, event):
        pass
