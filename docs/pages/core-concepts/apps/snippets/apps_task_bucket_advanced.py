import asyncio
from collections.abc import Callable

from hassette import App, AppConfig


class AdapterApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:make_async_adapter]
        # Normalize a sync-or-async callable into an async callable
        handler = self.task_bucket.make_async_adapter(self.maybe_sync_handler)
        await handler()  # always safe to await regardless of original type
        # --8<-- [end:make_async_adapter]

        # --8<-- [start:post_to_loop]
        # Schedule a callback on the event loop from any thread
        self.task_bucket.post_to_loop(self.on_data_ready, "sensor.temperature")
        # --8<-- [end:post_to_loop]

    def maybe_sync_handler(self) -> None:
        pass

    def on_data_ready(self, entity_id: str) -> None:
        pass


class SyncBridgeApp(App[AppConfig]):
    async def on_initialize(self):
        # --8<-- [start:run_sync]
        # Run an async coroutine from synchronous code (e.g., inside run_in_thread)
        state = self.task_bucket.run_sync(self.api.get_state("sensor.temperature"))
        # --8<-- [end:run_sync]
        self.logger.info("State: %s", state)
