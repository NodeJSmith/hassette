from hassette import App, AppConfig
from hassette.scheduler import Job


class RemoveApp(App[AppConfig]):
    my_job: Job | None = None

    async def on_initialize(self):
        # Store the job
        self.my_job = await self.scheduler.run_every(
            self.task, seconds=60, name="my_task"
        )

    async def remove_later(self):
        # Later...
        if self.my_job is not None:
            self.my_job.remove()

    async def task(self):
        pass
