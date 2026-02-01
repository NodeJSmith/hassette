from hassette import App


class LogbookApp(App):
    async def on_initialize(self):
        events = await self.api.get_logbook(
            entity_id="automation.morning_routine", start_time=self.now().subtract(hours=1), end_time=self.now()
        )
        self.logger.info("Events: %d", len(events))
