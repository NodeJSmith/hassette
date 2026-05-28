from hassette import App, AppConfig
from hassette.bus.error_context import BusErrorContext
from hassette.bus.event import RawStateChangeEvent


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.bus.on_error(self.on_bus_error)

        self.bus.on_state_change("light.kitchen", handler=self.on_light_change)

    async def on_bus_error(self, ctx: BusErrorContext) -> None:
        self.logger.error(
            "Handler failed for topic=%s: %s\n%s",
            ctx.topic,
            ctx.exception,
            ctx.traceback,
        )

    async def on_light_change(self, event: RawStateChangeEvent) -> None:
        raise ValueError("something went wrong")
