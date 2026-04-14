from hassette import App, AppConfig
from hassette.scheduler.classes import ScheduledJob


class PollApp(App[AppConfig]):
    _poll_job: ScheduledJob | None = None

    async def on_initialize(self):
        # Store a reference so the handler can cancel itself.
        self._poll_job = self.scheduler.run_every(
            self.wait_for_device,
            interval=10,
            name="device_poll",
        )

    async def wait_for_device(self):
        state = await self.api.get_state_or_none("sensor.device_status")
        if state is not None and not state.is_unavailable and state.value == "online":
            self.logger.info("Device is online — stopping poll")
            if self._poll_job is not None:
                self._poll_job.cancel()
                self._poll_job = None
