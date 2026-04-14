from hassette import App, AppConfig


class ThreadApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:run_in_thread]
        # Run a blocking function without freezing the event loop
        result = await self.task_bucket.run_in_thread(self.expensive_sync_call)
        # --8<-- [end:run_in_thread]

    def expensive_sync_call(self) -> str:
        return "result"
