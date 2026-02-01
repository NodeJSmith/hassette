from hassette import App, AppConfig, states
from hassette import dependencies as D


class MyApp(App[AppConfig]):
    async def on_initialize(self):
        self.logger.info("Getting started with Hassette!")
        self.bus.on_state_change("sun.*", handler=self.changed)
        self.scheduler.run_minutely(self.log_heartbeat, start=self.now())

    async def changed(self, new_state: D.StateNew[states.SunState]):
        self.logger.info("Sun changed: %s", new_state.value)

    async def log_heartbeat(self):
        self.logger.info("Heartbeat")
