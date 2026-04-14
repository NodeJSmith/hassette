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
        self.task_bucket.spawn(self.background_work(), name="background_work")

    async def background_work(self) -> None:
        # Offload blocking work to a thread
        result = await self.task_bucket.run_in_thread(self.blocking_library_call)
        self.logger.info("Result: %s", result)

    def blocking_library_call(self) -> str:
        # --8<-- [start:run_sync]
        # Inside a thread (run_in_thread or AppSync), call async code with run_sync
        state = self.task_bucket.run_sync(self.api.get_state("sensor.temperature"))
        # --8<-- [end:run_sync]
        return str(state.value)
