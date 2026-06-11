from hassette import App, AppSync


# For mostly async operations (recommended)
class MyAsyncApp(App):
    async def on_initialize(self):
        await self.api.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})


# For blocking/IO operations
class MySyncApp(AppSync):
    def on_initialize_sync(self):
        # The bus, scheduler, and API are async — reach their sync facades via .sync
        self.api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})
        self.bus.sync.on_state_change("light.kitchen", handler=self.on_change, name="kitchen")
        self.scheduler.sync.run_in(self.cleanup, 60, name="cleanup")

    def on_change(self, event): ...

    def cleanup(self): ...


# Mixed approach (offload blocking work)
class MyMixedApp(App):
    async def on_initialize(self):
        # Run blocking code in a thread
        result = await self.task_bucket.run_in_thread(self.blocking_work)

    def blocking_work(self):
        # This runs in a thread pool
        return expensive_computation()
