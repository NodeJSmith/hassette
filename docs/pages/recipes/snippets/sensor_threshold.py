from hassette import App, AppConfig, C, D, states


class ThresholdConfig(AppConfig):
    entity_id: str = "sensor.living_room_temperature"
    threshold: float = 28.0
    notify_target: str = "mobile_app_my_phone"


class SensorThresholdApp(App[ThresholdConfig]):
    """Alert when a sensor value exceeds a configured threshold."""

    async def on_initialize(self) -> None:
        self.bus.on_state_change(
            self.app_config.entity_id,
            handler=self.on_threshold_exceeded,
            changed_to=C.Comparison("gt", self.app_config.threshold),
        )

    async def on_threshold_exceeded(
        self,
        new_state: D.StateNew[states.SensorState],
        entity_id: D.EntityId,
    ) -> None:
        value = new_state.value
        unit = new_state.attributes.unit_of_measurement or ""
        name = new_state.attributes.friendly_name or entity_id

        self.logger.warning("%s crossed threshold: %s%s", name, value, unit)

        await self.api.call_service(
            "notify",
            self.app_config.notify_target,
            title="Sensor Alert",
            message=f"{name} is now {value}{unit} (threshold: {self.app_config.threshold}{unit})",
        )
