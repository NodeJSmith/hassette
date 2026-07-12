from hassette import App, AppConfig


class MorningApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.scheduler.run_daily(
            self.open_blinds, at="08:00", name="open_blinds", group="morning"
        )
        await self.scheduler.run_daily(
            self.play_music, at="08:05", name="play_music", group="morning"
        )
        await self.scheduler.run_daily(
            self.start_coffee, at="08:10", name="start_coffee", group="morning"
        )

    async def on_vacation_start(self) -> None:
        self.scheduler.cancel_group("morning")

    async def open_blinds(self) -> None: ...
    async def play_music(self) -> None: ...
    async def start_coffee(self) -> None: ...
