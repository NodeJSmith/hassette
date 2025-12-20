from hassette import App, dependencies as D, states


class TempApp(App):
    async def on_initialize(self):
        self.bus.on_state_change(
            "sensor.temperature",
            handler=self.on_temp_change,
            kwargs={"threshold": 75.0},
        )

    async def on_temp_change(
        self,
        new_state: D.StateNew[states.SensorState],
        threshold: float,  # From kwargs
    ):
        if new_state.attributes.temperature > threshold:
            self.logger.warning(
                "Temperature %.1f exceeds threshold %.1f",
                new_state.attributes.temperature,
                threshold,
            )
