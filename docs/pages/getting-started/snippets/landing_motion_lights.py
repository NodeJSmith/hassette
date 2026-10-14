from hassette import App, AppConfig


class MotionLightsConfig(AppConfig):
    motion_sensor: str = "binary_sensor.hallway_motion"
    light: str = "light.hallway"


class MotionLights(App[MotionLightsConfig]):
    async def on_initialize(self):
        sensor = self.app_config.motion_sensor
        await self.bus.on_state_change(
            sensor,
            changed_to="on",
            handler=self.lights_on,
            name="motion_on",
        )
        await self.bus.on_state_change(
            sensor,
            changed_to="off",
            duration=120,
            handler=self.lights_off,
            name="motion_off",
        )

    async def lights_on(self):
        await self.api.turn_on(self.app_config.light, brightness=200)

    async def lights_off(self):
        await self.api.turn_off(self.app_config.light)
