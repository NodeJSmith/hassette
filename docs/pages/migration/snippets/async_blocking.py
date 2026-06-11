import requests

from hassette import App


class BlockingWeatherApp(App):
    # --8<-- [start:blocking]
    async def update_forecast(self):
        # Holds the event loop until the request returns.
        # Every app is frozen for the duration.
        resp = requests.get("http://example.com/forecast", timeout=10)
        self.logger.info("Forecast: %s", resp.json())
    # --8<-- [end:blocking]


class OffloadedWeatherApp(App):
    # --8<-- [start:offload]
    async def update_forecast(self):
        # Runs in a thread pool; only this handler waits
        data = await self.task_bucket.run_in_thread(self.fetch_forecast)
        self.logger.info("Forecast: %s", data)

    def fetch_forecast(self):
        # A plain def holding the blocking call
        resp = requests.get("http://example.com/forecast", timeout=10)
        return resp.json()
    # --8<-- [end:offload]
