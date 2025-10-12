# another actual app that I use, not meant to be comparable to any AD example app

from hassette import App, AppConfig, StateChangeEvent, entities, states


class LaundryRoomLightAppConfig(AppConfig):
    toggle_entity: str = "input_boolean.ad_laundry_room_lights"
    light_entity: str = "light.laundry_room"
    motion_entity: str = "binary_sensor.motion_sensor_9b2a"
    brightness_cutoff: int = 50
    default_brightness: int = 26


class LaundryRoomLightsApp(App[LaundryRoomLightAppConfig]):
    toggle_entity: str = "input_boolean.ad_laundry_room_lights"

    async def toggle_enabled(self, event: StateChangeEvent[states.InputBooleanState]) -> None:
        """Handle toggling the enabled state of the app."""

        self.enabled = event.payload.data.new_state_value

    async def on_initialize(self) -> None:
        """Use the `on_initialize` lifecycle hook to set up the app."""
        self.prev_state = await self.api.get_state(self.app_config.light_entity, states.LightState)
        self.light_entity = await self.api.get_entity(self.app_config.light_entity, entities.LightEntity)

        self.bus.on_entity(self.app_config.motion_entity, handler=self.motion_detected, changed_to="on")
        self.bus.on_entity(self.app_config.motion_entity, handler=self.motion_cleared, changed_to="off")

        await self.set_enabled()

    async def set_enabled(self):
        try:
            self.enabled = (await self.api.get_state_value(self.toggle_entity)) == "on"
            self.bus.on_entity(self.toggle_entity, handler=self.toggle_enabled)
        except Exception:
            self.logger.exception("Error setting initial enabled state")
            self.enabled = True

    async def is_in_valid_state(self) -> bool:
        try:
            brightness = (await self.light_entity.refresh()).attributes.brightness or 0

            return brightness < self.app_config.brightness_cutoff
        except Exception:
            self.logger.exception("Error checking light brightness")
            return False

    async def motion_cleared(self, event: StateChangeEvent[states.BinarySensorState]) -> None:
        data = event.payload.data
        if not self.enabled:
            self.logger.info("%s is disabled", self.toggle_entity)
            return

        if not data.new_state or data.new_state_value is not False:
            self.logger.debug("Received motion detected event with no new state or state not 'off'")
            return

        if not await self.is_in_valid_state():
            return

        try:
            if not self.prev_state:
                self.logger.info("No state to revert to")
                return
            brightness = self.prev_state.attributes.brightness

            await self.light_entity.turn_on(brightness=brightness or self.app_config.default_brightness)
        except Exception:
            self.logger.exception("Error in motion_cleared")

    async def motion_detected(self, event: StateChangeEvent[states.BinarySensorState]) -> None:
        if not self.enabled:
            self.logger.info("%s is disabled", self.toggle_entity)
            return

        if not await self.is_in_valid_state():
            return

        # store the current state to revert to later
        self.prev_state = await self.api.get_state("light.laundry_room", states.LightState)

        try:
            brightness = (await self.light_entity.refresh()).attributes.brightness

            if brightness is None:
                self.logger.info("Brightness is None")
                return

            new_brightness = int(brightness * 1.5)

            await self.light_entity.turn_on(brightness=new_brightness)

        except Exception:
            self.logger.exception("Error in motion_detected")
