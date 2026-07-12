from hassette import App, AppConfig
from hassette.scheduler.error_context import SchedulerErrorContext


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        self.scheduler.on_error(self.on_job_error)

        await self.scheduler.run_every(
            self.check_sensors, minutes=5, name="check_sensors"
        )

    async def on_job_error(self, ctx: SchedulerErrorContext) -> None:
        self.logger.error(
            "Job '%s' failed: %s\n%s",
            ctx.job_name,
            ctx.exception,
            ctx.traceback,
        )

    async def check_sensors(self) -> None:
        raise ValueError("sensor unavailable")
