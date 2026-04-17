from hassette import App, AppConfig


class MyConfig(AppConfig):
    color_name: str = "red"


class NightLight(App[MyConfig]):
    # function which will be called at startup and reload
    async def on_initialize(self):
        # Schedule a daily callback that will call run_daily_callback() at 7pm every night
        job = self.scheduler.run_daily(self.run_daily_callback, at="19:00")
        self.logger.info("Scheduled job: %r", job)

        # 2025-10-13 19:57:02.670 INFO hassette.NightLight.0.on_initialize:11 - Scheduled job: ScheduledJob(name='run_daily_callback', owner=NightLight.0)

    # Our callback function will be called by the scheduler every day at 7pm
    async def run_daily_callback(self):
        # Call to Home Assistant to turn the porch light on
        await self.api.turn_on("light.office_light_1", color_name=self.app_config.color_name)
