from hassette import App, AppConfig, D, states


class MyAppConfig(AppConfig):
    greeting: str = "Hello from Hassette!"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
        self.bus.on_state_change("sun.*", handler=self.on_sun_change)
        self.scheduler.run_minutely(self.log_heartbeat, start=self.now())  # first run fires immediately

    async def on_sun_change(self, new_state: D.StateNew[states.SunState]):
        self.logger.info("Sun changed: %s", new_state.value)

        if new_state.value == "below_horizon":
            # Replace "light.porch" with an entity from your HA instance
            await self.api.turn_on("light.porch", domain="light")
            self.logger.info("Porch light turned on")

    async def log_heartbeat(self):
        self.logger.info("Heartbeat")
