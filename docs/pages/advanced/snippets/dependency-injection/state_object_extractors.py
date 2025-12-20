from hassette import App, dependencies as D, states


class LightApp(App):
    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],
        old_state: D.MaybeStateOld[states.LightState],
    ):
        if old_state:
            brightness_changed = new_state.attributes.brightness != old_state.attributes.brightness
            if brightness_changed:
                self.logger.info(
                    "Brightness: %s -> %s",
                    old_state.attributes.brightness,
                    new_state.attributes.brightness,
                )
