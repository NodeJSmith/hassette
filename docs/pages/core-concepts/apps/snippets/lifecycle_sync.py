from hassette import AppSync


class MyApp(AppSync):
    def on_initialize_sync(self) -> None:
        self.bus.sync.on_state_change("light.kitchen", handler=self.on_light_change, name="kitchen")
        self.scheduler.sync.run_in(self.cleanup_task, 60, name="cleanup")

    def on_light_change(self) -> None:
        pass

    def cleanup_task(self) -> None:
        pass
