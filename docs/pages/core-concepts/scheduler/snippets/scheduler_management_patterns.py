from hassette import App, AppConfig
from hassette.scheduler.classes import ScheduledJob


class ManagementPatternApp(App[AppConfig]):
    my_job: ScheduledJob | None = None

    async def on_initialize(self) -> None:
        self.my_job = await self.scheduler.run_every(self.check_sensors, minutes=5, group="morning")

    # --8<-- [start:cancel_group]
    async def cancel_morning_jobs(self) -> None:
        self.scheduler.cancel_group("morning")

    # --8<-- [end:cancel_group]

    # --8<-- [start:list_jobs]
    async def show_jobs(self) -> None:
        all_jobs = self.scheduler.list_jobs()  # pyright: ignore[reportUnusedVariable]

        morning_jobs = self.scheduler.list_jobs(group="morning")  # pyright: ignore[reportUnusedVariable]

    # --8<-- [end:list_jobs]

    # --8<-- [start:is_running]
    def is_running(self) -> bool:
        return self.my_job in self.scheduler.list_jobs()

    # --8<-- [end:is_running]

    # --8<-- [start:cancel_null]
    async def safe_cancel(self) -> None:
        if self.my_job is not None:
            self.my_job.cancel()
            self.my_job = None

    # --8<-- [end:cancel_null]

    async def check_sensors(self) -> None: ...
