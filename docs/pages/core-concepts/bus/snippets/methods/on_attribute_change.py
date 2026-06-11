from hassette import App, AppConfig, C, D, states


class VolumeMonitorApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:basic]
        await self.bus.on_attribute_change(
            "media_player.living_room",
            "volume_level",
            handler=self.on_volume_change,
            name="living_room_volume",
        )
        # --8<-- [end:basic]

        # --8<-- [start:changed_from_to]
        await self.bus.on_attribute_change(
            "sensor.phone_battery",
            "battery_level",
            changed_from=C.Comparison(">", 20),
            changed_to=C.Comparison("<=", 20),
            handler=self.on_battery_low,
            name="phone_battery_low",
        )
        # --8<-- [end:changed_from_to]

        # --8<-- [start:immediate]
        await self.bus.on_attribute_change(
            "climate.living_room",
            "current_temperature",
            handler=self.on_temp_change,
            immediate=True,
            name="climate_temp_init",
        )
        # --8<-- [end:immediate]

    async def on_volume_change(
        self, new: D.StateNew[states.MediaPlayerState]
    ) -> None:
        vol = new.attributes.volume_level
        self.logger.info("Volume changed to %s", vol)

    async def on_battery_low(
        self, new: D.StateNew[states.SensorState]
    ) -> None:
        self.logger.warning("Battery low: %s", new.value)

    async def on_temp_change(
        self, new: D.StateNew[states.ClimateState]
    ) -> None:
        temp = new.attributes.current_temperature
        self.logger.info("Room temperature: %s", temp)
