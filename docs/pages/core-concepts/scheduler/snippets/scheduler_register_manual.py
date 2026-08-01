from hassette import App, AppConfig
from hassette.scheduler import Job


class ReportApp(App[AppConfig]):
    report_job: Job | None = None

    async def on_initialize(self) -> None:
        # --8<-- [start:register]
        self.report_job = await self.scheduler.register(
            self.generate_report,
            name="generate_report",
        )
        # --8<-- [end:register]

    # --8<-- [start:submit]
    async def force_report_now(self) -> None:
        if self.report_job is not None:
            self.report_job.submit()

    # --8<-- [end:submit]

    async def generate_report(self) -> None:
        pass
