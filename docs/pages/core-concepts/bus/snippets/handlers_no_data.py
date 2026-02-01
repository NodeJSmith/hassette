from hassette import App


class HeartbeatApp(App):
    async def on_heartbeat(self) -> None:
        self.logger.info("Heartbeat received")
