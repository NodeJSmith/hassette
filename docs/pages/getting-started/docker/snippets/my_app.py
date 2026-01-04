from hassette import App, AppConfig


class MyAppConfig(AppConfig):
    greeting: str = "Hello from Docker!"


class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
