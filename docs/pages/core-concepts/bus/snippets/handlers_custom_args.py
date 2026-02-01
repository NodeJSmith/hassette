from hassette import App, D, states


class TempApp(App):
    async def on_initialize(self):
        self.bus.on_attribute_change(
            "climate.thermostat",
            "temperature",
            handler=self.on_temp_change,
            kwargs={"threshold": 75.0},
        )

    async def on_temp_change(self, new_state: D.StateNew[states.ClimateState], threshold: float):
        """Handle temperature changes and log if above threshold."""
        if new_state.attributes.temperature is None:
            self.logger.warning("No temperature attribute found")
            return

        if new_state.attributes.temperature > threshold:
            self.logger.warning(
                "Temperature %.1f exceeds threshold %.1f",
                new_state.attributes.temperature,
                threshold,
            )
