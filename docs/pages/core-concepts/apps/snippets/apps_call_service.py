from hassette import App, AppConfig


class CallServiceApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:call_service]
        await self.api.call_service("light", "turn_on", entity_id=self.app_config.light)
        # --8<-- [end:call_service]
