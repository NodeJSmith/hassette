from hassette import App, P


class HallwayButtonApp(App):
    async def on_initialize(self):
        # Ignore presses older than 10 seconds, including HA restart replays
        await self.bus.on_state_change(
            "event.hallway_button",
            handler=self.on_button_pressed,
            where=P.EventEntityFresh(max_age=10),
            name="hallway_button_pressed",
        )

    async def on_button_pressed(self):
        self.logger.info("Hallway button pressed")
