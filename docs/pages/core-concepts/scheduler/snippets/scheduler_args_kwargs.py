from hassette import App, AppConfig


class NotifyApp(App[AppConfig]):
    async def on_initialize(self):
        # Pass positional arguments to the handler
        self.scheduler.run_in(
            self.send_alert,
            delay=30.0,
            name="startup_alert",
            args=("Kitchen motion sensor", "triggered"),
        )

        # Pass keyword arguments to the handler
        self.scheduler.run_every(
            self.log_status,
            interval=300,
            name="status_log",
            kwargs={"level": "info", "include_history": True},
        )

        # Combine args and kwargs
        self.scheduler.run_daily(
            self.generate_report,
            name="daily_report",
            start=(6, 0),
            args=("daily",),
            kwargs={"recipients": ["admin"]},
        )

    async def send_alert(self, sensor: str, state: str):
        self.logger.info("Alert: %s is %s", sensor, state)

    async def log_status(self, level: str = "debug", include_history: bool = False):
        self.logger.info("Status logged (level=%s, history=%s)", level, include_history)

    async def generate_report(self, period: str, recipients: list[str]):
        self.logger.info("Generating %s report for %s", period, recipients)
