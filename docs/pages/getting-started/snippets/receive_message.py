from dataclasses import dataclass

from hassette import App, AppConfig, D


@dataclass
class TrackerDone:
    room: str


class TrackerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.bus.on_hassette_message(
            "tracker_done",
            handler=self.on_tracker_done,
            name="tracker_done",
        )

    async def on_tracker_done(
        self, data: D.MessageData[TrackerDone]
    ) -> None:
        self.logger.info("Tracker done in %s", data.room)
