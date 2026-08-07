from whenever import ZonedDateTime

from hassette import App, AppConfig

WeatherEntry = tuple[ZonedDateTime, dict]


class WeatherApp(App[AppConfig]):
    async def on_initialize(self):
        await self.scheduler.run_every(
            self.update_weather, seconds=60, name="weather_poll"
        )

    async def get_weather(self, location: str) -> dict:
        cache_key = f"weather:{location}"

        # Check cache first
        entry: WeatherEntry | None = await self.cache.get(cache_key)
        if entry is not None:
            cached_time, forecast = entry
            # Return the cached forecast if less than 30 minutes old
            if cached_time > self.now().subtract(minutes=30):
                self.logger.info("Using cached weather for %s", location)
                return forecast

        # Fetch a fresh forecast from the API
        self.logger.info("Fetching fresh weather for %s", location)
        forecast = await self.fetch_weather_api(location)
        await self.cache.set(cache_key, (self.now(), forecast))
        return forecast

    async def fetch_weather_api(self, location: str) -> dict:
        # Your external API call here
        return {"temperature": 72}

    async def update_weather(self):
        weather = await self.get_weather("New York")
        await self.api.set_state(
            "sensor.weather_forecast",
            str(weather["temperature"]),
        )
