from hassette import App, AppConfig
from hassette.scheduler import Cron, Daily, Every


class ScheduleExampleApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Fixed interval
        job = self.scheduler.schedule(self.check_sensors, Every(minutes=5))  # pyright: ignore[reportUnusedVariable]

        # Daily at a specific time
        job = self.scheduler.schedule(self.morning_routine, Daily(at="07:00"), group="morning")  # pyright: ignore[reportUnusedVariable]

        # Cron expression
        job = self.scheduler.schedule(self.workday_task, Cron("0 9 * * 1-5"))  # pyright: ignore[reportUnusedVariable]

    async def check_sensors(self) -> None: ...
    async def morning_routine(self) -> None: ...
    async def workday_task(self) -> None: ...
