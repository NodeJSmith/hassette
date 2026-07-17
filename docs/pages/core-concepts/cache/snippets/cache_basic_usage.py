from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self):
        # Store data
        await self.cache.set("last_run", self.now())
        await self.cache.set(
            "user_preferences", {"theme": "dark", "notifications": True}
        )

        # Retrieve data
        last_run = await self.cache.get("last_run")
        if last_run is not None:
            self.logger.info("Last run: %s", last_run)

        # Get with default value
        count = await self.cache.get("run_count", default=0) or 0
        await self.cache.set("run_count", count + 1)

        # Delete data
        await self.cache.delete("old_key")
