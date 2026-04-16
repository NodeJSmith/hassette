from hassette import App, AppConfig


class DailyApp(App[AppConfig]):
    async def on_initialize(self):
        # Every day at midnight (default)
        self.scheduler.run_daily(self.task, name="task_daily")

        # Every day at 7:00 AM (wall-clock, DST-safe)
        self.scheduler.run_daily(self.morning_routine, at="07:00", name="morning_routine")

    async def task(self):
        pass

    async def morning_routine(self):
        pass
