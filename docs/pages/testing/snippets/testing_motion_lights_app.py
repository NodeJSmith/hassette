from hassette import App, AppConfig


class MotionLightsConfig(AppConfig):
    motion_entity: str
    light_entity: str


class MotionLights(App[MotionLightsConfig]):
    async def on_initialize(self):
        await self.bus.on_state_change(
            self.app_config.motion_entity,
            changed_to="on",
            handler=self.lights_on,
            name="motion_on",
        )

    async def lights_on(self):
        await self.api.turn_on(self.app_config.light_entity)
