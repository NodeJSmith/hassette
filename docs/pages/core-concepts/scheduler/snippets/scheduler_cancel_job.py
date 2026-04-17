from hassette import App, AppConfig


class CancelApp(App[AppConfig]):
    async def on_initialize(self):
        # Store the job
        self.my_job = self.scheduler.run_every(self.task, seconds=60)

    async def cancel_later(self):
        # Later...
        self.my_job.cancel()

    async def task(self):
        pass
