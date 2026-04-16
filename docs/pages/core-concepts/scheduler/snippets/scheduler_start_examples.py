from hassette import App, AppConfig


class StartParamApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:start_examples]
        # Run every hour
        self.scheduler.run_hourly(self.task, name="hourly_task")

        # Run daily at 7:00 AM (wall-clock, DST-safe)
        self.scheduler.run_daily(self.task, at="07:00", name="morning_task")

        # Run once at a calculated future time
        from hassette.scheduler import Once

        next_week = self.now().add(days=7)
        self.scheduler.schedule(self.task, Once(at=next_week), name="next_week_task")
        # --8<-- [end:start_examples]

    async def task(self):
        pass
