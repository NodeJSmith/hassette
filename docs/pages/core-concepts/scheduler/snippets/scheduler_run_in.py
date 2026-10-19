from hassette import App, AppConfig


class DelayApp(App[AppConfig]):
    async def on_initialize(self):
        # Run in 5 seconds
        await self.scheduler.run_in(self.turn_off_light, delay=5, name="turn_off_light")

        # Run in 10 minutes
        await self.scheduler.run_in(self.check_status, minutes=10, name="check_status")

        # Run in 1 hour 30 minutes (the components add together)
        await self.scheduler.run_in(self.check_status, hours=1, minutes=30, name="check_status_later")

    async def turn_off_light(self):
        pass

    async def check_status(self):
        pass
