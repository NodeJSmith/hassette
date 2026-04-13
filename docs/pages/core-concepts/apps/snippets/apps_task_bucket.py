import asyncio

from hassette import App, AppConfig


class TaskBucketApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:spawn]
        # Fire off a background coroutine — the bucket tracks and cancels it on shutdown
        self.task_bucket.spawn(self.poll_sensor(), name="poll_sensor")
        # --8<-- [end:spawn]

        # --8<-- [start:run_in_thread]
        # Run a blocking call without freezing the event loop
        data = await self.task_bucket.run_in_thread(self.expensive_sync_call)
        self.logger.info("Got: %s", data)
        # --8<-- [end:run_in_thread]

    async def poll_sensor(self):
        while True:
            await asyncio.sleep(60)

    def expensive_sync_call(self) -> str:
        return "result"
