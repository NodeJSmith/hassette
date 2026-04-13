from hassette import App, AppConfig


class OptimizedApp(App[AppConfig]):
    async def on_initialize(self):
        # Load from disk cache once into an instance variable
        self.config_data: dict = self.cache.get("config", {})  # pyright: ignore[reportAttributeAccessIssue]

        # Use the in-memory copy throughout the app's lifetime
        setting = self.config_data.get("some_setting")
        self.logger.info("Setting: %s", setting)

    async def on_shutdown(self):
        # Persist changes back to disk cache at shutdown
        self.cache["config"] = self.config_data
