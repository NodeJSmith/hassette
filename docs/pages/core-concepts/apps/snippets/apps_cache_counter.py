from hassette import App, AppConfig


class CacheApp(App[AppConfig]):
    counter: int

    async def on_initialize(self):
        # --8<-- [start:cache_counter]
        # Load counter from cache, defaulting to 0
        self.counter = self.cache.get("counter", 0)

        # Increment and save back
        self.counter += 1
        self.cache["counter"] = self.counter
        # --8<-- [end:cache_counter]
