from hassette import App, AppConfig


class IdempotentApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:idempotent_registration]
        # Safe to call on every reload — won't create duplicates
        await self.scheduler.run_every(
            self.check_sensors,
            seconds=60,
            name="sensor_check",
            if_exists="skip",
        )
        # --8<-- [end:idempotent_registration]

        # --8<-- [start:replace_registration]
        # Use replace when the trigger or handler may change between reloads
        await self.scheduler.run_every(
            self.check_sensors,
            seconds=120,
            name="sensor_check",
            if_exists="replace",
        )
        # --8<-- [end:replace_registration]

    async def check_sensors(self):
        pass
