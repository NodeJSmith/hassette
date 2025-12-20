from hassette import App


class IntervalApp(App):
    async def on_initialize(self):
        # Every 10 seconds
        self.scheduler.run_every(self.poll_api, interval=10)

        # Every hour (3600 seconds)
        self.scheduler.run_every(self.hourly_check, interval=3600)

    async def poll_api(self):
        pass

    async def hourly_check(self):
        pass
