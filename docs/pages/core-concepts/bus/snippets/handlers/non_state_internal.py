from hassette import App, AppConfig


class MonitorApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_websocket_connected(
            handler=self.on_connected,
            name="ws_connected",
        )
        await self.bus.on_websocket_disconnected(
            handler=self.on_disconnected,
            name="ws_disconnected",
        )

    async def on_connected(self) -> None:
        self.logger.info("WebSocket connection established")

    async def on_disconnected(self) -> None:
        self.logger.warning("WebSocket connection lost")
