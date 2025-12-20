from hassette import App, dependencies as D, states


class MyApp(App):
    async def on_light_change(
        self,
        new_state: D.StateNew[states.LightState],  # Automatically converted
    ):
        # new_state is already a LightState instance
        brightness = new_state.attributes.brightness
