from hassette import App, AppConfig


class AlarmApp(App[AppConfig]):
    async def on_initialize(self):
        # Run once at 7:30 AM today (or tomorrow if already past)
        self.scheduler.run_once(self.morning_alarm, at="07:30", name="morning_alarm")

    async def morning_alarm(self):
        self.logger.info("Good morning!")
