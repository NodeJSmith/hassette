from hassette import App, AppConfig


class MyAppConfig(AppConfig):
    # Define fields with types and optional defaults
    location_name: str
    threshold: float = 25.0
    notify_target: str = "mobile_app_phone"


# Pass the config class to the App generic
class MyApp(App[MyAppConfig]):
    async def on_initialize(self):
        # self.app_config is typed as MyAppConfig
        self.logger.info("Starting %s monitoring", self.app_config.location_name)
