from hassette import App, AppConfig


class IdempotentApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:idempotent_registration]
        # Safe to call on every reload — won't create duplicates
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp_changed,
            name="outdoor_temp",
            if_exists="skip",
        )
        # --8<-- [end:idempotent_registration]

        # --8<-- [start:replace_registration]
        # Use replace when the handler or filter may change between reloads
        await self.bus.on_state_change(
            "sensor.outdoor_temperature",
            handler=self.on_temp_changed,
            name="outdoor_temp",
            if_exists="replace",
        )
        # --8<-- [end:replace_registration]

    async def on_temp_changed(self):
        pass
