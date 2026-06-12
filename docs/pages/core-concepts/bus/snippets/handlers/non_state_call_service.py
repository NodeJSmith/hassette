from hassette import App, AppConfig, D


class LightControlApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_call_service(
            "light",
            "turn_on",
            handler=self.on_light_turn_on,
            name="light_turn_on",
        )

    async def on_light_turn_on(self, entity_id: D.EntityId) -> None:
        self.logger.info("Light turned on: %s", entity_id)
