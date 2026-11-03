from hassette import App, AppConfig


class ForecastApp(App[AppConfig]):
    default_cache_ttl = 3600  # seconds; applies to every set() without a ttl

    async def on_initialize(self) -> None:
        forecast = {"high": 74, "low": 58}
        await self.cache.set("forecast", forecast)  # expires in 1 hour
