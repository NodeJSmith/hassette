from hassette import App, AppConfig
from hassette.events import CallServiceEvent


class MyConfig(AppConfig):
    button_entity: str = "input_button.test_button"


class MyApp(App[MyConfig]):
    async def on_initialize(self):
        sub = self.bus.on_call_service(
            service="press", handler=self.minimal_callback, where={"entity_id": self.app_config.button_entity}
        )
        self.logger.info("Subscribed: %s", sub)

    def minimal_callback(self, event: CallServiceEvent) -> None:
        self.logger.info("Button pressed: %s", event.payload.data.service_data)
