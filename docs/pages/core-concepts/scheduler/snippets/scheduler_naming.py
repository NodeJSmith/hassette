from hassette import App


class NamedJobApp(App):
    async def on_initialize(self):
        self.scheduler.run_every(
            self.tick,
            interval=60,
            name="heartbeat_monitor",
        )

    async def tick(self):
        pass
