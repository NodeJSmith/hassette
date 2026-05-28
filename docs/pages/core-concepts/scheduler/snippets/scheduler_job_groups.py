from hassette import App, AppConfig


class MorningApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.scheduler.run_daily(self.open_blinds, at="08:00", group="morning")
        self.scheduler.run_daily(self.play_music, at="08:05", group="morning")
        self.scheduler.run_daily(self.start_coffee, at="08:10", group="morning")

    async def on_vacation_start(self) -> None:
        self.scheduler.cancel_group("morning")

    async def open_blinds(self) -> None: ...
    async def play_music(self) -> None: ...
    async def start_coffee(self) -> None: ...
