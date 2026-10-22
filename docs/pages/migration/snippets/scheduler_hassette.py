from hassette import App, AppConfig


class MyConfig(AppConfig):
    color_name: str = "red"


class NightLight(App[MyConfig]):
    async def on_initialize(self):
        await self.scheduler.run_daily(
            self.light_on,
            at="19:00",
            name="porch_light_on",
            kwargs={"entity_id": "light.porch"},
        )

    async def light_on(self, entity_id: str):
        await self.api.turn_on(
            entity_id, color_name=self.app_config.color_name
        )
