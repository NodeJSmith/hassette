from typing import Annotated

from hassette import App
from hassette.events import RawStateChangeEvent


def get_friendly_name(event: RawStateChangeEvent) -> str:
    """Extract friendly_name from new state attributes."""
    new_state = event.payload.data.new_state
    if new_state and "attributes" in new_state:
        return new_state["attributes"].get("friendly_name", "Unknown")
    return "Unknown"


class MyCustomExtractorApp(App):
    async def on_initialize(self):
        await self.bus.on_state_change(
            "light.kitchen",
            handler=self.on_friendly_name_change,
            name="kitchen_friendly_name",
        )

    async def on_friendly_name_change(
        self,
        name: Annotated[str, get_friendly_name],
    ):
        self.logger.info("Changed: %s", name)
