from hassette import App, C


class ClimateApp(App):
    async def on_initialize(self):
        # --8<-- [start:threshold_crossing]
        await self.bus.on_state_change(
            "sensor.living_room_temperature",
            handler=self.on_too_warm,
            changed=C.CrossedAbove(25),
            name="living_room_too_warm",
        )
        # --8<-- [end:threshold_crossing]

    async def on_too_warm(self):
        pass
