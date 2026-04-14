from hassette import App, AppConfig


class DailyApp(App[AppConfig]):
    async def on_initialize(self):
        # Every day at default start time (now)
        self.scheduler.run_daily(self.task, name="task_daily")

        # Every day at 7:00 AM (using start parameter)
        self.scheduler.run_daily(self.morning_routine, start=(7, 0), name="morning_routine")

    async def task(self):
        pass

    async def morning_routine(self):
        pass
