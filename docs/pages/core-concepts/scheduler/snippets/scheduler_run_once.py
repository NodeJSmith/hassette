from hassette import App, AppConfig


class AlarmApp(App[AppConfig]):
    async def on_initialize(self):
        # Run at a specific time today
        self.scheduler.run_once(self.morning_alarm, start=(7, 30), name="morning_alarm")

    async def morning_alarm(self):
        self.logger.info("Good morning!")
