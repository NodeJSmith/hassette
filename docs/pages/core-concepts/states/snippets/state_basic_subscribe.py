from hassette import App, AppConfig, D, states


class ThermostatApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp_change,
            name="outdoor_temp",
        )

    async def on_temp_change(
        self,
        new: D.StateNew[states.SensorState],
    ) -> None:
        self.logger.info("Temperature: %s", new.value)
