from hassette import App


class WeatherApp(App):
    async def on_initialize(self):
        response = await self.api.call_service(
            "weather",
            "get_forecasts",
            target={"entity_id": "weather.home"},
            type="daily",
        )
        print(response)
