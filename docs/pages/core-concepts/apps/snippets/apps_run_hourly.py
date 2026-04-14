from hassette import App, AppConfig


class HourlyApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:run_hourly]
        self.scheduler.run_hourly(self.log_status)
        # --8<-- [end:run_hourly]

    async def log_status(self):
        pass
