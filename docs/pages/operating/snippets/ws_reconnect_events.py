from hassette import App, AppConfig, Topic


class ReconnectAwareApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.paused = False
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

    async def on_ha_disconnected(self) -> None:
        self.logger.warning("HA disconnected, pausing")
        self.paused = True

    async def on_ha_connected(self) -> None:
        self.paused = False
        # Events missed during the outage are not replayed,
        # so read the current state and act on it.
        door = self.states.binary_sensor.get("binary_sensor.front_door")
        if door is not None and door.value is False:
            await self.api.turn_off("light.porch")
