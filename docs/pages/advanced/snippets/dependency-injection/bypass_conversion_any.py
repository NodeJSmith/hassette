from typing import Annotated, Any

from hassette import App
from hassette import accessors as A


class RawApp(App):
    async def handler(
        self,
        # No conversion - receive raw value
        raw_value: Annotated[Any, A.get_attr_new("brightness")],
    ):
        # Handle conversion yourself
        brightness = int(raw_value) if raw_value else None
        self.logger.info("Brightness: %s", brightness)
