from hassette import App, AppConfig


class CronApp(App[AppConfig]):
    async def on_initialize(self):
        # Weekdays at 9 AM (5-field standard cron: minute hour dom month dow)
        await self.scheduler.run_cron(self.work_start, "0 9 * * 1-5")

        # Every 15 minutes
        await self.scheduler.run_cron(self.check, "*/15 * * * *")

        # First of the month at midnight
        await self.scheduler.run_cron(self.monthly_job, "0 0 1 * *")

    async def work_start(self):
        pass

    async def check(self):
        pass

    async def monthly_job(self):
        pass
