from typing import Any

from hassette import App, AppConfig, Topic
from hassette.events import Event


class TopicApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic=Topic.HASS_EVENT_AUTOMATION_TRIGGERED,
            handler=self.on_automation,
            name="automation_triggered",
        )

    async def on_automation(self, event: Event[Any]) -> None:
        self.logger.info("Topic: %s", event.topic)
