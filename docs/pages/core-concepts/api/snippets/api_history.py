from hassette import App


class HistoryApp(App):
    async def on_initialize(self):
        start = self.now().subtract(hours=24)
        history = await self.api.get_history("sensor.temperature", start_time=start)

        for entry in history:
            print(f"{entry.last_changed}: {entry.state}")
