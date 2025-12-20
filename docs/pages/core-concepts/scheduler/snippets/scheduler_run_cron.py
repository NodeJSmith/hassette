from hassette import App


class CronApp(App):
    async def on_initialize(self):
        # Weekdays at 9 AM
        self.scheduler.run_cron(
            self.work_start,
            hour=9,
            minute=0,
            day_of_week="1-5",
        )

        # Every 15 minutes
        self.scheduler.run_cron(self.check, minute="*/15")

        # First of the month at midnight
        self.scheduler.run_cron(
            self.monthly_job,
            day_of_month=1,
            hour=0,
            minute=0,
        )

    async def work_start(self):
        pass

    async def check(self):
        pass

    async def monthly_job(self):
        pass
