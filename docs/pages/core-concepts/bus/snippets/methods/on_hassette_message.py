from dataclasses import dataclass

from hassette import App, AppConfig, D


@dataclass
class TrackerDone:
    room: str
    count: int = 1


class TrackerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:subscribe]
        await self.bus.on_hassette_message(
            "tracker_done",
            handler=self.on_tracker_done,
            name="tracker_done",
        )
        # --8<-- [end:subscribe]

    async def on_tracker_done(
        self, data: D.MessageData[TrackerDone]
    ) -> None:
        self.logger.info("%s done %d times", data.room, data.count)
