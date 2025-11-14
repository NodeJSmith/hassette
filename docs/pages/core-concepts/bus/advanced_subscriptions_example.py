from hassette import App
from hassette.types.enums import ResourceStatus


class AdvancedSubscriptionsExample(App):
    async def on_initialize(self):
        # Direct topic subscription
        self.bus.on(topic="hass.event.automation_triggered", handler=self.on_automation)

        # Hassette framework events
        self.bus.on_hassette_service_status(status=ResourceStatus.FAILED, handler=self.on_service_failure)
        self.bus.on_hassette_service_crashed(handler=self.on_any_crash)

    async def on_automation(self, event):
        pass

    async def on_service_failure(self, event):
        pass

    async def on_any_crash(self, event):
        pass
