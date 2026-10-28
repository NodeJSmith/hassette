from hassette import App, AppConfig


class RestartAwareApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:subscribe]
        await self.bus.on(
            topic="hass.event.homeassistant_started",
            handler=self.on_ha_started,
            name="my_app.ha_started",
        )
        # --8<-- [end:subscribe]

    async def on_ha_started(self) -> None:
        self.logger.info("Home Assistant restarted")
