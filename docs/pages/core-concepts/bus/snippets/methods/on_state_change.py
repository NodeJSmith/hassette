from hassette import App, AppConfig, C, D, states


class LightMonitorApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:basic]
        await self.bus.on_state_change(
            "light.kitchen",
            handler=self.on_light_change,
            name="kitchen_light",
        )
        # --8<-- [end:basic]

        # --8<-- [start:immediate]
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp,
            immediate=True,
            name="outdoor_temp_init",
        )
        # --8<-- [end:immediate]

        # --8<-- [start:duration]
        await self.bus.on_state_change(
            "light.kitchen",
            changed_to="on",
            handler=self.on_light_on_long,
            duration=1800.0,
            name="kitchen_light_duration",
        )
        # --8<-- [end:duration]

        # --8<-- [start:changed_to]
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            changed_to=C.Comparison(">", 25),
            handler=self.on_temp_high,
            name="outdoor_temp_high",
        )
        # --8<-- [end:changed_to]

    async def on_light_change(
        self, new: D.StateNew[states.LightState]
    ) -> None:
        self.logger.info("Light is now: %s", new.value)

    async def on_temp(
        self, new: D.StateNew[states.SensorState]
    ) -> None:
        self.logger.info("Temperature: %s", new.value)

    async def on_light_on_long(self) -> None:
        self.logger.info("Kitchen light on for 30 minutes")

    async def on_temp_high(
        self, new: D.StateNew[states.SensorState]
    ) -> None:
        self.logger.warning("High temperature: %s", new.value)
