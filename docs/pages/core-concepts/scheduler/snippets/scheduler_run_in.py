from hassette import App


class DelayApp(App):
    async def on_initialize(self):
        # Run in 5 seconds
        self.scheduler.run_in(self.turn_off_light, delay=5.0)

        # Run in 10 minutes (using TimeDelta or seconds)
        self.scheduler.run_in(self.check_status, delay=600)

    async def turn_off_light(self):
        pass

    async def check_status(self):
        pass
