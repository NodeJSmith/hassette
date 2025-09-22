from hassette import App, AppConfig
from hassette.core.events import StateChangeEvent
from hassette.models.entities import LightEntity
from hassette.models.states import InputButtonState, LightState


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


class MyApp(App[MyAppUserConfig]):
    async def initialize(self) -> None:
        await super().initialize()

        print(self.app_config_cls)
        print(self.app_config)

        self.logger.info("MyApp has been initialized")
        self.hassette.bus.on_entity("input_button.test", handler=self.handle_event_sync)
        self.hassette.scheduler.run_in(self.hassette.api.get_states, 1)

        self.office_light_exists = await self.hassette.api.entity_exists("light.office")
        self.test_button_exists = await self.hassette.api.entity_exists("input_button.test")

    async def test_reload_app(self):
        await self.hassette._app_handler.reload_app(self.app_manifest.app_key)

    async def test_stuff(self) -> None:
        if self.office_light_exists:
            self.light_state = await self.hassette.api.get_state("light.office", model=LightState)
            self.light_entity = await self.hassette.api.get_entity("light.office", model=LightEntity)
        elif self.test_button_exists:
            self.button_state = await self.hassette.api.get_state("input_button.test", model=InputButtonState)
            self.logger.info("Button state: %s", self.button_state)

    def handle_event_sync(self, event: StateChangeEvent) -> None:
        self.logger.info("event: %s", event)
        test = self.hassette.api.sync.get_state_value("input_button.test")
        self.logger.info("state: %s", test)

    async def handle_event(self, event: StateChangeEvent) -> None:
        self.logger.info("Async event: %s", event)
        test = await self.hassette.api.get_state_value("input_button.test")
        self.logger.info("Async state: %s", test)
