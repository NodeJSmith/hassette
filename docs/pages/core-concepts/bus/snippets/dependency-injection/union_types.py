from hassette import App, D, states


class SensorApp(App):
    async def on_sensor_change(
        self,
        new: D.StateNew[
            states.SensorState | states.BinarySensorState
        ],
        entity_id: D.EntityId,
    ):
        if isinstance(new, states.SensorState):
            self.logger.info("Sensor %s: %s", entity_id, new.value)
        else:
            self.logger.info("Binary %s: %s", entity_id, new.value)
