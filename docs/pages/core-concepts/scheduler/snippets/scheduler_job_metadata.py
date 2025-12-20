from hassette import App


class JobApp(App):
    async def on_initialize(self):
        job = self.scheduler.run_daily(self.task)
        self.logger.info("Task scheduled for: %s", job.next_run)

    async def task(self):
        pass
