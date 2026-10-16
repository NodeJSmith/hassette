from whenever import TimeDelta

from hassette import App, AppConfig
from hassette.scheduler import EntityTime


class WakeUpApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:alarm]
        await self.scheduler.schedule(
            self.start_the_day,
            EntityTime("sensor.phone_next_alarm"),
            name="phone_alarm",
        )
        # --8<-- [end:alarm]

        # --8<-- [start:offset_daily]
        await self.scheduler.schedule(
            self.preheat_coffee,
            EntityTime(
                "input_datetime.morning_routine",
                offset=TimeDelta(minutes=-30),
                daily=True,
            ),
            name="preheat_coffee",
        )
        # --8<-- [end:offset_daily]

        # --8<-- [start:attribute]
        await self.scheduler.schedule(
            self.open_blinds,
            EntityTime("sun.sun", attribute="next_dawn"),
            name="open_blinds_at_dawn",
        )
        # --8<-- [end:attribute]

        # --8<-- [start:sun_offset]
        await self.scheduler.schedule(
            self.porch_lights_on,
            EntityTime(
                "sun.sun",
                attribute="next_setting",
                offset=TimeDelta(minutes=-30),
            ),
            name="porch_lights_before_sunset",
        )
        # --8<-- [end:sun_offset]

    async def start_the_day(self) -> None: ...

    async def preheat_coffee(self) -> None: ...

    async def open_blinds(self) -> None: ...

    async def porch_lights_on(self) -> None: ...
