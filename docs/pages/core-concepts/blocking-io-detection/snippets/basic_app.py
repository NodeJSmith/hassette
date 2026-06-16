import asyncio

from hassette import App, AppConfig


class SensorAppConfig(AppConfig):
    app_key: str = "sensor_app"
    sensor_entity: str = "sensor.outdoor_temperature"


class SensorApp(App[SensorAppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            self.app_config.sensor_entity,
            handler=self.on_reading,
            name="outdoor_temp_reading",
        )

    async def on_reading(self) -> None:
        # Reading state asynchronously — no blocking I/O here.
        state = await self.api.get_state(self.app_config.sensor_entity)
        self.logger.info("Temperature: %s", state)
