from hassette import App, AppConfig
from hassette.bus.error_context import BusErrorContext
from hassette.events import RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            on_error=self.on_temp_error,
            name="temp_sensor",
        )

    async def on_temp_error(self, ctx: BusErrorContext) -> None:
        self.logger.warning("Temperature handler failed: %s", ctx.exception)

    async def on_temp_change(self, event: RawStateChangeEvent) -> None:
        raise RuntimeError("temp sensor error")
