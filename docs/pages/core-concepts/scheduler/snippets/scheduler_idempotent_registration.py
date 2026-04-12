from hassette import App, AppConfig


class IdempotentApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:idempotent_registration]
        # Safe to call on every reload — won't create duplicates
        self.scheduler.run_every(
            self.check_sensors,
            60,
            name="sensor_check",
            if_exists="skip",
        )
        # --8<-- [end:idempotent_registration]

    async def check_sensors(self):
        pass
