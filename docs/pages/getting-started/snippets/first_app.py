from hassette import App, AppConfig
from hassette.events import RawStateChangeEvent


class MyAppConfig(AppConfig):
    greeting: str = "Hello from Hassette!"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
        self.bus.on_state_change("sun.*", handler=self.on_sun_change)
        self.scheduler.run_minutely(self.log_heartbeat, start=self.now())  # first run fires immediately

    async def on_sun_change(self, event: RawStateChangeEvent):
        new_state = event.payload.data.new_state
        self.logger.info("Sun changed: %s", new_state.get("state") if new_state else "unknown")

    async def log_heartbeat(self):
        self.logger.info("Heartbeat")
