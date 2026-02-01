from hassette import App, states
from hassette import dependencies as D


class SensorApp(App):
    async def on_sensor_change(
        self, new_state: D.StateNew[states.SensorState | states.BinarySensorState], entity_id: D.EntityId
    ):
        # new_state is automatically converted to the correct type
        # based on the entity's domain
        if isinstance(new_state, states.SensorState):
            self.logger.info("Sensor %s: %s", entity_id, new_state.value)
        elif isinstance(new_state, states.BinarySensorState):
            self.logger.info("Binary sensor %s: %s", entity_id, new_state.value)
