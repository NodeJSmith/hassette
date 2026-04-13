from hassette import App, AppConfig


class HourlyApp(App[AppConfig]):
    async def on_initialize(self):
        # Every hour
        self.scheduler.run_hourly(self.task, name="task_hourly")

        # Every 4 hours
        self.scheduler.run_hourly(self.task, hours=4, name="task_every_4h")

    async def task(self):
        pass
