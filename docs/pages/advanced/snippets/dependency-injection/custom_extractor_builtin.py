from typing import Annotated

from hassette import App, accessors as A


class LightApp(App):
    async def on_light_change(
        self,
        brightness: Annotated[float | None, A.get_attr_new("brightness")],
        color_temp: Annotated[int | None, A.get_attr_new("color_temp")],
    ):
        self.logger.info("Brightness: %s, Color temp: %s", brightness, color_temp)
