from hassette import App, AppConfig


class StartParamApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:start_examples]
        # Run every hour, starting 60 seconds from now
        self.scheduler.run_hourly(self.task, start=60)

        # Run daily, starting at 7:00 AM
        self.scheduler.run_daily(self.task, start=(7, 0))

        # Run once at a calculated future time
        next_week = self.now().add(days=7)
        self.scheduler.run_once(self.task, start=next_week)
        # --8<-- [end:start_examples]

    async def task(self):
        pass
