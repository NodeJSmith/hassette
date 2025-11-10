from hassette import App


class HistoryExample(App):
    async def history_example(self):
        history = await self.api.get_history("climate.living_room", start_time=self.now().subtract(hours=2))
        for entry in history:
            self.logger.debug("%s -> %s", entry.last_changed, entry.state)

        logbook = await self.api.get_logbook("binary_sensor.front_door", start_time=self.now().subtract(hours=2))
        return history, logbook
