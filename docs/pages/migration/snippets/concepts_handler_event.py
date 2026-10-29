from hassette import App
from hassette.events import RawStateChangeEvent


class KitchenApp(App):
    async def on_light_change(self, event: RawStateChangeEvent): ...
