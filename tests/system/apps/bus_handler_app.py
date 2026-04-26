"""Bus-handler app fixture for system tests."""

from hassette import App
from hassette.events import RawStateChangeEvent


class BusHandlerApp(App):
    """App that captures state-change events for light.kitchen_lights.

    Used to verify that the bus delivers real HA events to app-registered handlers.
    """

    async def on_initialize(self) -> None:
        self.captured_events: list[RawStateChangeEvent] = []
        self.bus.on_state_change("light.kitchen_lights", handler=self._on_light_change)

    async def _on_light_change(self, event: RawStateChangeEvent) -> None:
        self.captured_events.append(event)
