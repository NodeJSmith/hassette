from hassette import App, AppConfig


class RemoveApp(App[AppConfig]):
    async def on_initialize(self):
        # Store the job
        self.my_job = await self.scheduler.run_every(
            self.task, seconds=60, name="my_task"
        )

    async def remove_later(self):
        # Later...
        self.my_job.remove()

    async def task(self):
        pass
