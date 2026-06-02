from typing import Any

from hassette import App, AppConfig
from hassette.events import Event


class ScriptApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic="hass.event.automation_triggered",
            handler=self.on_automation,
            name="automation_triggered",
        )

    async def on_automation(self, event: Event[Any]) -> None:
        self.logger.info("Automation fired: %s", event.topic)
