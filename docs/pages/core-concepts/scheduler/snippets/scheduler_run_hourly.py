from hassette import App, AppConfig


class HourlyApp(App[AppConfig]):
    async def on_initialize(self):
        # Every hour
        self.scheduler.run_hourly(self.task)

        # Every 4 hours
        self.scheduler.run_hourly(self.task, hours=4)

    async def task(self):
        pass
