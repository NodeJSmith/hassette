from hassette import App, AppConfig
from hassette.scheduler.error_context import SchedulerErrorContext


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        await self.scheduler.run_every(
            self.sync_data,
            minutes=10,
            name="sync_data",
            on_error=self.on_sync_error,
        )

    async def on_sync_error(self, ctx: SchedulerErrorContext) -> None:
        self.logger.warning("Sync failed: %s", ctx.exception)

    async def sync_data(self) -> None:
        raise RuntimeError("sync error")
