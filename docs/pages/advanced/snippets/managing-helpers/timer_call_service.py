from hassette import App, AppConfig


class TimerApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # --8<-- [start:timer]
        await self.api.call_service("timer", "start", target={"entity_id": "timer.away_mode"})
        # --8<-- [end:timer]
