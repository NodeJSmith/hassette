from hassette import A, App, P


class NaptimeButtonApp(App):
    async def on_initialize(self):
        # Ignore HA restart replays, restart-time placeholder states, and entity removal
        await self.bus.on_state_change(
            "input_button.naptime",
            handler=self.on_button_pressed,
            where=(
                P.EventEntityFresh(max_age=10)
                & P.IsPresent(A.get_state_value_new)
                & ~P.StateTo("unavailable")
                & ~P.StateTo("unknown")
            ),
            name="naptime_button_pressed",
        )

    async def on_button_pressed(self):
        self.logger.info("Naptime button pressed")
