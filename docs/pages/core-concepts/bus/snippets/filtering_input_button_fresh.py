from hassette import App, P


class NaptimeButtonApp(App):
    async def on_initialize(self):
        # Ignore HA restart replays and restart-time placeholder states
        await self.bus.on_state_change(
            "input_button.naptime",
            handler=self.on_button_pressed,
            where=(
                P.EventEntityFresh(max_age=10)
                & ~P.StateTo("unavailable")
                & ~P.StateTo("unknown")
            ),
            name="naptime_button_pressed",
        )

    async def on_button_pressed(self):
        self.logger.info("Naptime button pressed")
