from hassette import App, AppConfig
from hassette.scheduler.triggers import Daily


class JitterApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:jitter]
        # Spread the actual fire time by up to 30 seconds
        self.scheduler.schedule(self.check_sensors, Daily(at="06:00"), jitter=30)
        # --8<-- [end:jitter]

    async def check_sensors(self) -> None: ...
