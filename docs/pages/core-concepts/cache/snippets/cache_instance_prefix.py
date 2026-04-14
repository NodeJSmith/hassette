from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Prefix keys with instance_name to avoid collisions
        # when the same app class runs as multiple instances
        cache_key = f"{self.app_config.instance_name}:last_run"
        self.cache[cache_key] = self.now()
