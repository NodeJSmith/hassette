from hassette import App, AppConfig


class IntervalApp(App[AppConfig]):
    async def on_initialize(self):
        # Every 10 seconds
        self.scheduler.run_every(self.poll_api, seconds=10, name="poll_api")

        # Every hour (using hours parameter)
        self.scheduler.run_every(self.hourly_check, hours=1, name="hourly_check")

    async def poll_api(self):
        pass

    async def hourly_check(self):
        pass
