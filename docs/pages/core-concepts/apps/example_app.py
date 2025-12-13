from pydantic import Field

from hassette import App, AppConfig
from hassette import dependencies as D


class MyAppConfig(AppConfig):
    light: str = Field(..., description="The entity to monitor")


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.on_change_listener = self.bus.on_state_change(self.app_config.light, handler=self.on_change)
        self.minutely_logger = self.scheduler.run_minutely(self.log_every_minute)

    async def on_change(self, new_state: D.StateNew, old_state: D.StateOld, entity_id: D.EntityId):
        self.logger.info("Entity %s changed: %s", self.app_config.light, entity_id)
        self.logger.info("Old state: %s", old_state)
        self.logger.info("New state: %s", new_state)

    async def log_every_minute(self):
        self.logger.info("One minute passed")

    async def on_shutdown(self):
        # not required, as Hassette will clean up all resources automatically
        # but shown here for demonstration
        self.on_change_listener.cancel()
        self.minutely_logger.cancel()
