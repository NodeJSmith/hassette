import os
from typing import Annotated

from hassette import App, AppConfig
from hassette import dependencies as D
from hassette.events import RawStateChangeEvent
from hassette.models import states
from hassette.models.entities import LightEntity
from hassette.models.states import InputButtonState, LightState


class MyAppUserConfig(AppConfig):
    test_entity: str = "input_button.test"


class MyApp(App[MyAppUserConfig]):
    async def on_initialize(self) -> None:
        if "PYTEST_VERSION" in os.environ:
            # Skip initialization during tests
            return

        self.logger.info("MyApp is initializing")
        self.bus.on_state_change("input_button.test", handler=self.handle_event_sync)
        self.scheduler.run_in(self.api.get_states, 1)
        self.scheduler.run_every(
            self.scheduled_job_example, 10, args=("value1", "value2"), kwargs={"kwarg1": "kwarg_value"}
        )

        self.office_light = self.states.light.get("light.office")
        self.test_button = self.states.input_button.get("input_button.test")
        self.office_light_exists = self.office_light is not None
        self.test_button_exists = self.test_button is not None

        if self.office_light:
            self.logger.info("Office light exists: %s", self.office_light)
        if self.test_button:
            self.logger.info("Test button exists: %s", self.test_button)

    async def test_reload_app(self):
        await self.hassette._app_handler.reload_app(self.app_manifest.app_key)

    async def test_stuff(self) -> None:
        if self.office_light_exists:
            self.light_state: LightState = await self.api.get_state("light.office")
            self.light_entity = await self.api.get_entity("light.office", model=LightEntity)
        elif self.test_button_exists:
            self.button_state = await self.api.get_state("input_button.test", model=InputButtonState)
            self.logger.info("Button state: %s", self.button_state)

    def handle_event_sync(
        self,
        new_state: D.StateNew[states.InputButtonState],
        old_state: D.StateOld[states.InputButtonState],
        friendly_name: Annotated[str, D.AttrNew("friendly_name")],
        **kwargs,
    ) -> None:
        if new_state is None:
            raise ValueError("new_state should not be None in handle_event_sync")

        if old_state is None:
            raise ValueError("old_state should not be None in handle_event_sync")

        self.logger.info("new_state: %s, kwargs: %s, friendly_name: %s", new_state, kwargs, friendly_name)
        test = self.api.sync.get_state_value("input_button.test")
        self.logger.info("state: %s", test)

    async def handle_event(self, event: RawStateChangeEvent, **kwargs) -> None:
        self.logger.info("Async event: %s, kwargs: %s", event, kwargs)
        test = await self.api.get_state_value("input_button.test")
        self.logger.info("Async state: %s", test)

    async def scheduled_job_example(self, test_value: str, test_value2: str, *, kwarg1: str | None = None):
        self.logger.info(
            "Scheduled job executed with test_value=%s, test_value2=%s, kwarg1=%s", test_value, test_value2, kwarg1
        )
