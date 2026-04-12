from hassette import App, AppConfig


class WeatherApp(App[AppConfig]):
    async def on_initialize(self):
        self.scheduler.run_every(self.update_weather, 60)

    async def update_weather(self):
        weather = await self.get_weather("New York")
        await self.api.set_state(
            "sensor.weather_forecast",
            str(weather["temperature"]),
        )

    async def get_weather(self, location: str) -> dict:
        cache_key = f"weather:{location}"

        # Check cache first
        if cache_key in self.cache:
            cached_time, data = self.cache[cache_key]
            # Return cached data if less than 30 minutes old
            if cached_time > self.now().subtract(minutes=30):
                self.logger.info("Using cached weather for %s", location)
                return data

        # Fetch fresh data from API
        self.logger.info("Fetching fresh weather for %s", location)
        data = await self.fetch_weather_api(location)
        self.cache[cache_key] = (self.now(), data)
        return data

    async def fetch_weather_api(self, location: str) -> dict:
        # Your external API call here
        return {"temperature": 72}
