from datetime import UTC, datetime

from hassette import App


class SchedulerBasicExample(App):
    async def refresh_sensors(self) -> None:
        await self.api.call_service("sensor", "refresh")

    def log_heartbeat(self) -> None:
        self.logger.info("Still alive at %s", datetime.now(UTC))

    def setup(self) -> None:
        self.scheduler.run_every(self.refresh_sensors, interval=300)
        self.scheduler.run_in(self.log_heartbeat, delay=30)
