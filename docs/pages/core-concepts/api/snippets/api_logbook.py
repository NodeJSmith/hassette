from hassette import App


class LogbookApp(App):
    async def on_initialize(self):
        events = await self.api.get_logbook(
            start=self.now().subtract(hours=1),
            entity_id="automation.morning_routine",
        )
        self.logger.info("Events: %d", len(events))
