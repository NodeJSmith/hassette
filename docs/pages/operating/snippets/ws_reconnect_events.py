from typing import Any

from hassette import App, AppConfig, Topic
from hassette.events import Event


class ReconnectAwareApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:subscribe]
        await self.bus.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_DISCONNECTED,
            handler=self.on_ha_disconnected,
            name="my_app.ha_disconnect",
        )
        await self.bus.on(
            topic=Topic.HASSETTE_EVENT_WEBSOCKET_CONNECTED,
            handler=self.on_ha_connected,
            name="my_app.ha_connect",
        )
        # --8<-- [end:subscribe]

    async def on_ha_disconnected(self, event: Event[Any]) -> None:
        self.logger.warning("HA disconnected")

    async def on_ha_connected(self, event: Event[Any]) -> None:
        self.logger.info("HA reconnected")
