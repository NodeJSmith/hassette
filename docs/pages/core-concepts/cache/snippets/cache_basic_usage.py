from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Store data
        self.cache["last_run"] = self.now()
        self.cache["user_preferences"] = {"theme": "dark", "notifications": True}

        # Retrieve data
        if "last_run" in self.cache:
            last_run = self.cache["last_run"]
            self.logger.info("Last run: %s", last_run)

        # Get with default value
        count = self.cache.get("run_count", 0)
        self.cache["run_count"] = count + 1

        # Delete data
        if "old_key" in self.cache:
            del self.cache["old_key"]
