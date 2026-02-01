from hassette import App, D, states


class MyApp(App):
    async def on_light_change(self, new_state: D.StateNew[states.LightState]):
        # new_state is already a LightState instance
        pass
