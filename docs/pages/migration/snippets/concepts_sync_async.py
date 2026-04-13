from hassette import App, AppSync


# For mostly async operations (recommended)
class MyAsyncApp(App):
    async def on_initialize(self):
        await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})


# For blocking/IO operations
class MySyncApp(AppSync):
    def on_initialize_sync(self):
        # Use sync API
        self.api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})


# Mixed approach (offload blocking work)
class MyMixedApp(App):
    async def on_initialize(self):
        # Run blocking code in a thread
        result = await self.task_bucket.run_in_thread(self.blocking_work)

    def blocking_work(self):
        # This runs in a thread pool
        return expensive_computation()
