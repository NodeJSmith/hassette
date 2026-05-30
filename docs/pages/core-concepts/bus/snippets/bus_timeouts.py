from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Override the global timeout for a slow handler
        await self.bus.on_state_change(
            "sensor.weather",
            handler=self.fetch_forecast,
            timeout=30.0,  # 30 seconds instead of the global default
            name="weather_forecast",
        )

        # Disable timeout for a handler that legitimately runs long
        await self.bus.on_state_change(
            "input_boolean.run_backup",
            handler=self.run_full_backup,
            timeout_disabled=True,
            name="backup_trigger",
        )

    async def fetch_forecast(self, event: RawStateChangeEvent) -> None: ...
    async def run_full_backup(self, event: RawStateChangeEvent) -> None: ...
