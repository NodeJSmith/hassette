from hassette import App, D, states


class KitchenApp(App):
    async def on_light_change(self, new_state: D.StateNew[states.LightState]): ...
