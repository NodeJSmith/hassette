from hassette import App, AppConfig


class ExampleAppConfig(AppConfig):
    greeting: str = "Hello from Hassette! Edit example_app.py in the apps folder of the add-on's config folder."


class ExampleApp(App[ExampleAppConfig]):
    async def on_initialize(self):
        self.logger.info(self.app_config.greeting)
