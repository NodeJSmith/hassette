from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        payload = {"temp": 72, "humidity": 45}
        # --8<-- [start:expire]
        self.cache.set("weather_data", payload, expire=3600)  # expires in 1 hour
        # --8<-- [end:expire]
