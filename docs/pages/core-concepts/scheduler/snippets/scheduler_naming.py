from hassette import App, AppConfig


class NamedJobApp(App[AppConfig]):
    async def on_initialize(self):
        self.scheduler.run_every(
            self.tick,
            seconds=60,
            name="heartbeat_monitor",
        )

    async def tick(self):
        pass
