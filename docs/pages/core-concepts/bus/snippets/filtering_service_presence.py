from hassette import App
from hassette.const import ANY_VALUE


class LightApp(App):
    async def on_initialize(self):
        # Key presence: brightness must exist, value doesn't matter
        self.bus.on_call_service(
            domain="light",
            service="turn_on",
            where={"brightness": ANY_VALUE},
            handler=self.on_brightness_set,
        )

    async def on_brightness_set(self, event):
        pass
