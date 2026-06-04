from hassette import App


class HelperApp(App):
    async def on_initialize(self):
        # --8<-- [start:turn_on]
        await self.api.turn_on(
            "light.kitchen", brightness=255, color_name="blue"
        )
        # --8<-- [end:turn_on]

        # --8<-- [start:turn_off]
        await self.api.turn_off("switch.fan")
        # --8<-- [end:turn_off]

        # --8<-- [start:toggle]
        await self.api.toggle_service("light.bedroom")
        # --8<-- [end:toggle]
