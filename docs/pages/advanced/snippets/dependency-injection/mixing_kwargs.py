from hassette import App, states
from hassette import dependencies as D


class TempApp(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            kwargs={"threshold": 75.0, "message": "Temperature %s (%.1f°F) exceeds threshold %.1f°F"},
        )

    async def on_temp_change(
        self, new_state: D.StateNew[states.SensorState], entity_id: D.EntityId, threshold: float, message: str
    ):
        temp = float(new_state.value) if new_state.value else 0.0
        if temp > threshold:
            self.logger.warning(message, entity_id, temp, threshold)
