from hassette import App, AppConfig


class UtilitiesApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:fire_event]
        await self.api.fire_event(
            "custom_event",
            {"source": "my_app", "value": 42},
        )

        # event_data is optional
        await self.api.fire_event("hassette_ready")
        # --8<-- [end:fire_event]

        # --8<-- [start:set_state]
        await self.api.set_state(
            "sensor.custom_score",
            "87",
            {"unit_of_measurement": "%"},
        )
        # --8<-- [end:set_state]

        # --8<-- [start:get_calendars]
        calendars = await self.api.get_calendars()
        for cal in calendars:
            print(cal["entity_id"], cal.get("name"))
        # --8<-- [end:get_calendars]

        # --8<-- [start:get_calendar_events]
        start = self.now()
        end = self.now().add(days=7)
        events = await self.api.get_calendar_events("calendar.work", start, end)
        for event in events:
            print(event["summary"], event["start"])
        # --8<-- [end:get_calendar_events]
