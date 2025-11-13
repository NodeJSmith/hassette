from hassette import App


class MorningRoutine(App):
    async def on_initialize(self) -> None:
        # Run every weekday at 07:15.
        self.scheduler.run_cron(self.prepare_coffee, minute=15, hour=7, day_of_week="mon-fri", name="brew")

        # Poll a sensor every 2 minutes starting 10 seconds from now.
        self.scheduler.run_every(self.refresh_sensors, interval=120, start=10, name="sensor-poll")

        # Fire a one-off reminder in 45 seconds.
        self.scheduler.run_in(self._log_reminder, delay=45, name="reminder")

    async def prepare_coffee(self) -> None:
        await self.api.call_service("switch", "turn_on", {"entity_id": "switch.espresso"})

    async def refresh_sensors(self) -> None:
        await self.api.call_service("sensor", "refresh")

    def _log_reminder(self) -> None:
        self.logger.info("Stretch your legs!", extra={"job": "reminder"})
