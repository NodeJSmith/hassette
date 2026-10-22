from hassette import App, AppConfig, D

from .shared import LightsSyncedData


class ReceiverApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on(
            topic="lights_synced",
            handler=self.on_lights_synced,
            name="lights_synced_log",
        )

    async def on_lights_synced(
        self,
        data: D.EventData[LightsSyncedData],
    ) -> None:
        self.logger.info("Synced by %s", data.source)
