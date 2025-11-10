from hassette import App, AppConfig


class HelloWorldConfig(AppConfig):
    greeting: str = "Hello, World!"


class HelloWorld(App[HelloWorldConfig]):
    async def on_initialize(self) -> None:
        self.logger.info(self.app_config.greeting)

        # Show it's actually connected to HA
        self.scheduler.run_every(self.log_sun_state, interval=30)

    async def log_sun_state(self) -> None:
        sun_state = await self.api.get_state("sun.sun")
        self.logger.info("Sun is currently: %s", sun_state.state)
