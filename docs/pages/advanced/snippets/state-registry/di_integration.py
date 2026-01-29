from hassette import App, states
from hassette import dependencies as D


class MyApp(App):
    async def on_light_change(self, new_state: D.StateNew[states.LightState]):
        # new_state is already a LightState instance
        pass
