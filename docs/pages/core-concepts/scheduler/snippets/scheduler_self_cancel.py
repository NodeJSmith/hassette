from hassette import App, AppConfig
from hassette.scheduler.classes import ScheduledJob


class PollApp(App[AppConfig]):
    poll_job: ScheduledJob | None

    async def on_initialize(self):
        self.poll_job = await self.scheduler.run_every(
            self.wait_for_device,
            seconds=10,
            name="device_poll",
        )

    async def wait_for_device(self):
        state = await self.api.get_state_or_none("sensor.device_status")
        if state is not None and not state.is_unavailable and state.value == "online":
            self.logger.info("Device is online, stopping poll")
            if self.poll_job is not None:
                self.poll_job.cancel()
                self.poll_job = None
