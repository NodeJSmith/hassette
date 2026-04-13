from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class MyAppConfig(AppConfig):
    greeting: str = "Hello from Hassette!"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
        self.bus.on_state_change("sun.*", handler=self.on_sun_change)

    # --8<-- [start:raw_handler]
    async def on_sun_change(self, event: RawStateChangeEvent):
        new_state = event.payload.data.new_state
        value = new_state.get("state") if new_state else "unknown"
        self.logger.info("Sun changed: %s", value)

        if value == "below_horizon":
            await self.api.turn_on("light.porch", domain="light")
            self.logger.info("Porch light turned on")
    # --8<-- [end:raw_handler]
