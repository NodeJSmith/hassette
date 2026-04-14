from hassette import App, AppConfig


class MinutelyApp(App[AppConfig]):
    async def on_initialize(self):
        # Every minute
        self.scheduler.run_minutely(self.task, name="task_minutely")

        # Every 5 minutes
        self.scheduler.run_minutely(self.task, minutes=5, name="task_every_5m")

    async def task(self):
        pass
