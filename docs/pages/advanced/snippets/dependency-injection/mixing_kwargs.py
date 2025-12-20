from hassette import App, dependencies as D, states


class TempApp(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            kwargs={"threshold": 75.0, "alert_level": "warning"},
        )

    async def on_temp_change(
        self,
        new_state: D.StateNew[states.SensorState],
        entity_id: D.EntityId,
        threshold: float,  # From kwargs
        alert_level: str,  # From kwargs
    ):
        temp = float(new_state.state) if new_state.state else 0.0
        if temp > threshold:
            self.logger.log(
                alert_level,
                "Temperature %s (%.1f°F) exceeds threshold %.1f°F",
                entity_id,
                temp,
                threshold,
            )
