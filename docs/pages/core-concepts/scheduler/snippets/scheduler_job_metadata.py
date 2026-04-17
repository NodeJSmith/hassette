from hassette import App, AppConfig


class JobApp(App[AppConfig]):
    async def on_initialize(self):
        job = self.scheduler.run_every(self.task, seconds=60, name="my_task")
        self.logger.info("Scheduled: %s", job.name)
        self.logger.info("Next run:  %s", job.next_run)
        self.logger.info("Trigger:   %s", job.trigger)
        self.logger.info("Job ID:    %s", job.job_id)

    async def task(self):
        pass
