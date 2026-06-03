from hassette import App, AppConfig, D


class LightAuditApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_call_service(
            "light",
            handler=self.on_light_service,
            name="light_service_audit",
        )

    async def on_light_service(
        self,
        entity_id: D.EntityId,
    ) -> None:
        self.logger.info("Light service called on: %s", entity_id)
