from hassette import App


class LogbookApp(App):
    async def on_initialize(self):
        end = self.now()
        start = end.subtract(hours=1)
        events = await self.api.get_logbook(
            entity_id="automation.morning_routine",
            start_time=start,
            end_time=end,
        )
        self.logger.info("Events: %d", len(events))
