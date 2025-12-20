from typing import Annotated

from hassette import App, accessors as A


class LightApp(App):
    async def on_light_change(
        self,
        # Extractor returns string "200" from HA
        # TypeRegistry automatically converts to int
        brightness: Annotated[int | None, A.get_attr_new("brightness")],
        # Extractor returns string "on" from HA
        # TypeRegistry automatically converts to bool
        is_on: Annotated[bool, A.get_state_value_new],
    ):
        if is_on and brightness and brightness > 200:
            self.logger.info("Light is very bright: %d", brightness)
