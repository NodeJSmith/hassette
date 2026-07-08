from hassette import App, AppConfig


class MorningApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:where_state]
        await self.scheduler.run_daily(
            self.morning_routine,
            at="07:00",
            name="morning_routine",
            where=self.home_is_occupied,
        )
        # --8<-- [end:where_state]

    def home_is_occupied(self) -> bool:
        state = self.states.binary_sensor.get("home_occupied")
        return state is not None and state.value is True

    async def morning_routine(self):
        pass
