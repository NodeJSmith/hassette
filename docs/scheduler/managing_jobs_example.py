from hassette import App


class ManagingJobsExample(App):
    async def on_initialize(self):
        job = self.scheduler.run_every(self.refresh_sensors, interval=60, name="poll")
        self.logger.debug("Next run at %s", job.next_run)

        # Later during teardown or when conditions change
        job.cancel()

    async def refresh_sensors(self):
        await self.api.call_service("sensor", "refresh")
