import os

from hassette import AppConfig, AppSync
from hassette.events import RawStateChangeEvent
from hassette.models.entities import LightEntity


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


class MyAppSync(AppSync):
    def on_initialize_sync(self) -> None:
        if "PYTEST_VERSION" in os.environ:
            # Skip initialization during tests
            return

        self.bus.on_state_change("input_button.*", handler=self.handle_event)
        self.scheduler.run_in(self.test_stuff, 1)

        self.office_light_exists = self.api.sync.entity_exists("light.office")
        self.test_button_exists = self.api.sync.entity_exists("input_button.test")

    def test_stuff(self) -> None:
        if self.office_light_exists:
            self.light_state = self.states.light.get("office")
            self.light_entity = self.api.sync.get_entity("light.office", LightEntity)
        elif self.test_button_exists:
            self.button_state = self.states.input_button.get("test")
            self.logger.info("Button state: %s", self.button_state)

    def handle_event(self, event: RawStateChangeEvent) -> None:
        self.logger.info("event: %s", event)
        test = self.states.input_button.get("test")
        self.logger.info("state: %s", test)

        test_2 = self.states.input_button.get("input_button.test")
        self.logger.info("state 2: %s", test_2)
