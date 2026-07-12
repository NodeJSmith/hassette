from hassette import App, AppConfig
from hassette.scheduler import Cron, Daily, Every


class ScheduleExampleApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        # Fixed interval
        job = await self.scheduler.schedule(
            self.check_sensors, Every(minutes=5), name="check_sensors"
        )

        # Daily at a specific time
        job = await self.scheduler.schedule(
            self.morning_routine,
            Daily(at="07:00"),
            name="morning_routine",
            group="morning",
        )

        # Cron expression
        job = await self.scheduler.schedule(
            self.workday_task, Cron("0 9 * * 1-5"), name="workday_task"
        )

    async def check_sensors(self) -> None: ...
    async def morning_routine(self) -> None: ...
    async def workday_task(self) -> None: ...
