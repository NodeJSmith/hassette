from hassette import App, AppConfig
from hassette.scheduler import Job


class ManagementPatternApp(App[AppConfig]):
    my_job: Job | None = None

    async def on_initialize(self) -> None:
        self.my_job = await self.scheduler.run_every(
            self.check_sensors, minutes=5, name="check_sensors", group="morning"
        )

    # --8<-- [start:remove_group]
    async def remove_morning_jobs(self) -> None:
        self.scheduler.remove_group("morning")

    # --8<-- [end:remove_group]

    # --8<-- [start:list_jobs]
    async def show_jobs(self) -> None:
        all_jobs = self.scheduler.list_jobs()
        self.logger.info("All jobs: %r", all_jobs)

        morning_jobs = self.scheduler.list_jobs(group="morning")
        self.logger.info("Morning jobs: %r", morning_jobs)

    # --8<-- [end:list_jobs]

    # --8<-- [start:is_running]
    def is_running(self) -> bool:
        return self.my_job in self.scheduler.list_jobs()

    # --8<-- [end:is_running]

    # --8<-- [start:remove_null]
    async def safe_remove(self) -> None:
        if self.my_job is not None:
            self.my_job.remove()
            self.my_job = None

    # --8<-- [end:remove_null]

    async def check_sensors(self) -> None: ...
