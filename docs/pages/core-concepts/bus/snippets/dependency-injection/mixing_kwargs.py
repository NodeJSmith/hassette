from hassette import App, D, states


class TempApp(App):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            kwargs={"threshold": 75.0},
            name="temp_threshold",
        )

    async def on_temp_change(
        self,
        new: D.StateNew[states.SensorState],
        entity_id: D.EntityId,
        threshold: float,
    ):
        temp = float(new.value) if new.value else 0.0
        if temp > threshold:
            self.logger.warning(
                "%s is %.1f°F (threshold: %.1f)",
                entity_id,
                temp,
                threshold,
            )
