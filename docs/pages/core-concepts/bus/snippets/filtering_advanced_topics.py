from hassette import App, Topic


class CustomEventApp(App):
    async def on_initialize(self):
        # Subscribe to a custom internal event
        await self.bus.on(topic="my_custom_event", handler=self.on_custom_event, name="custom_event")

        # Subscribe to specific raw HA event
        await self.bus.on(topic=Topic.HASS_EVENT_CALL_SERVICE, handler=self.on_any_service, name="any_service")

    async def on_custom_event(self, event):
        pass

    async def on_any_service(self, event):
        pass
