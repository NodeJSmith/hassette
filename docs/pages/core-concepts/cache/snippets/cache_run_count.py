from hassette import App, AppConfig


class MyApp(App[AppConfig]):
    async def on_initialize(self) -> None:
        run_count = await self.cache.get("run_count", default=0) + 1
        await self.cache.set("run_count", run_count)
        self.logger.info("Run count: %s", run_count)
