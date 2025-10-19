# another actual app that I use, not meant to be comparable to any AD example app

from typing import ClassVar

from deepdiff import DeepDiff

from hassette import AppConfig, AppSync, StateChangeEvent, entities, states
from hassette import predicates as P
from hassette.events import CallServiceEvent


class OfficeButtonAppConfig(AppConfig):
    office_light: str = "light.office"
    event_action: str = "event.office_button_action"


class OfficeButtonApp(AppSync[OfficeButtonAppConfig]):
    lights: ClassVar[dict[str, states.LightState]] = {}

    def get_office_light(self) -> states.LightState:
        """Get the office light entity."""
        return self.api.sync.get_state(self.app_config.office_light, states.LightState)

    def on_initialize_sync(self) -> None:
        self.enabled = True

        self.bus.on_state_change(self.app_config.event_action, handler=self.handle_office_button)
        self.bus.on_call_service(
            domain="light",
            handler=self.log_manual_light_service,
            where=P.ServiceDataWhere.from_kwargs(entity_id=P.IsOrContains(self.app_config.office_light)),
        )

        attributes = self.get_office_light().attributes
        if not isinstance(attributes.entity_id, list):
            self.logger.warning(
                "Office light entity attributes.entity_id is not a list: %r",
                attributes.entity_id,
            )
            return

        for entity_id in self.get_office_light().attributes.entity_id:  # type: ignore
            entity = self.api.sync.get_state(entity_id, states.LightState)
            self.lights[entity_id] = entity
            self.bus.on_state_change(entity_id, handler=self.log_light_changes)

    def log_light_changes(self, event: StateChangeEvent[states.LightState]) -> None:
        """Log changes to light entities."""
        new_state = event.payload.data.new_state
        if not new_state:
            self.logger.warning("Received light state change event with no new state: %r", event)
            return

        diff = DeepDiff(
            self.lights.get(new_state.entity_id),
            new_state,
            ignore_order=True,
            exclude_paths=["root.context"],
        )
        if diff:
            self.logger.debug("Light %s changed:\n%s", new_state.entity_id, diff.pretty())
            self.lights[new_state.entity_id] = new_state
        else:
            self.logger.debug("No significant changes for light %r", new_state.entity_id)

    def log_manual_light_service(self, event: CallServiceEvent) -> None:
        """Log light-related service calls that include the configured office light."""
        service_data = event.payload.data.service_data
        self.logger.debug(
            "Observed %s.%s for %s",
            event.payload.data.domain,
            event.payload.data.service,
            service_data.get("entity_id"),
        )

    async def handle_office_button(self, event: StateChangeEvent[states.EventState]) -> None:
        """Handle the office button action."""
        if not self.enabled:
            self.logger.info("Office Button is disabled")
            return

        new_state = event.payload.data.new_state

        if not new_state or not new_state.attributes:
            self.logger.warning(
                "Received office button action event with no new state or attributes: %r",
                event,
            )
            return

        new_state_type = new_state.attributes.event_type or ""

        self.logger.info("Office Button Action: %s", new_state_type)

        light_entity = await self.api.get_entity("light.office", entities.LightEntity)
        current_state = light_entity.value

        if current_state not in ("on", "off"):
            self.logger.warning("Office light is in an unexpected state: %r", current_state)
            return

        if current_state == "off":
            self.logger.info("Light is currently off, turning on to bright/white")
            await light_entity.turn_on(brightness=255, rgb_color=(255, 255, 255))
            return

        if new_state_type == "hold":
            self.logger.info("Button held, resetting light to bright/white")
            await light_entity.turn_on(brightness=255, rgb_color=(255, 255, 255), effect="blink")
            return

        self.logger.info("Light is currently on, turning off")
        await light_entity.turn_off()
