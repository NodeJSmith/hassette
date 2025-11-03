from pydantic import Field

from hassette import App, AppConfig


class PresenceConfig(AppConfig):
    motion_sensor: str = Field(...)
    lights: list[str] = Field(default_factory=list)


class Presence(App[PresenceConfig]):
    async def on_initialize(self):
        self.bus.on_state_change(self.app_config.motion_sensor, handler=self.on_motion, changed_to="on")

    async def on_motion(self, event):
        for light in self.app_config.lights:
            await self.api.turn_on(light)
