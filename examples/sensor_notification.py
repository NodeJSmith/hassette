from hassette import App, AppConfig, StateChangeEvent, states


class SensorNotificationAppConfig(AppConfig):
    sensor: str | list[str] | None = None
    idle_state: str = "Idle"
    turn_on: str = "scene.house_bright"
    input_select: str | list[str] | None = None

    @property
    def sensor_as_list(self):
        if not self.sensor:
            return []
        if isinstance(self.sensor, list):
            return self.sensor
        return [self.sensor]

    @property
    def input_select_as_list(self):
        if not self.input_select:
            return []
        if isinstance(self.input_select, list):
            return self.input_select
        return [self.input_select]


class SensorNotification(App[SensorNotificationAppConfig]):
    async def initialize(self):
        if self.app_config.sensor is None:
            return

        sensors = self.app_config.sensor if isinstance(self.app_config.sensor, list) else [self.app_config.sensor]
        for sensor in sensors:
            self.bus.on_entity(sensor, handler=self.state_change)

    async def state_change(self, event: StateChangeEvent[states.SensorState]):
        data = event.payload.data
        if not data.new_state:
            return

        friendly_name = data.new_state.attributes.friendly_name if data.new_state.attributes else data.entity_id
        new = data.new_state_value

        if new != "":
            if self.app_config.input_select_as_list:
                valid_modes = self.app_config.input_select_as_list
                select = valid_modes.pop(0)
                is_state = await self.api.get_state_value(select)
            else:
                is_state = None
                valid_modes = ()

            self.logger.info("%s changed to %s", friendly_name, new)
            # self.notify(f"{friendly_name} changed to {new}", name=globals.notify)

            if new != self.app_config.idle_state and self.app_config.turn_on and is_state in valid_modes:
                await self.api.turn_on(self.app_config.turn_on)
