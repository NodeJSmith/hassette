import asyncio

from hassette import App, AppConfig


class SensorAppConfig(AppConfig):
    app_key: str = "sensor_app"
    data_file: str = "/data/readings.txt"


class SensorApp(App[SensorAppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_reading,
            name="outdoor_temp_reading",
        )

    async def on_reading(self) -> None:
        state = await self.api.get_state("sensor.outdoor_temperature")
        # Run blocking file I/O on a worker thread — loop stays responsive.
        await asyncio.to_thread(self._write_reading, str(state))

    def _write_reading(self, value: str) -> None:
        """Sync helper — runs on a thread pool worker, not the loop thread."""
        with open(self.app_config.data_file, "a") as f:
            f.write(f"{value}\n")
