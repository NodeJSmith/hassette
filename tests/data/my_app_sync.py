from hassette import AppConfig, AppSync
from hassette.events import StateChangeEvent
from hassette.models.entities import LightEntity
from hassette.models.states import InputButtonState, LightState

# from hassette.core.apps.app import only


try:
    from .my_app import MyApp
except ImportError:
    from my_app import MyApp  # type: ignore


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


# @only
class MyAppSync(AppSync):
    def initialize_sync(self) -> None:
        self.bus.on_entity("input_button.test", handler=self.handle_event)
        self.scheduler.run_in(self.test_stuff, 1)

        self.office_light_exists = self.api.sync.entity_exists("light.office")
        self.test_button_exists = self.api.sync.entity_exists("input_button.test")

    def test_stuff(self) -> None:
        my_app = self.hassette.get_app("my_app", 0)
        assert isinstance(my_app, MyApp), f"Expected MyApp, got {type(my_app)}"

        if self.office_light_exists:
            self.light_state = self.api.sync.get_state("light.office", model=LightState)
            self.light_entity = self.api.sync.get_entity("light.office", model=LightEntity)
        elif self.test_button_exists:
            self.button_state = self.api.sync.get_state("input_button.test", model=InputButtonState)
            self.logger.info("Button state: %s", self.button_state)

    def handle_event(self, event: StateChangeEvent) -> None:
        self.logger.info("event: %s", event)
        test = self.api.sync.get_state_value("input_button.test")
        self.logger.info("state: %s", test)
