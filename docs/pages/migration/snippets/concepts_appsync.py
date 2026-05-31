from hassette import AppSync
from hassette.events import RawStateChangeEvent


class MyApp(AppSync):
    def on_initialize_sync(self) -> None:
        # The bus, scheduler, and API are async — reach their sync facades via .sync
        self.api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})
        self.bus.sync.on_state_change("light.kitchen", handler=self.on_change, name="kitchen")
        self.scheduler.sync.run_in(self.cleanup, 60, name="cleanup")

    def on_change(self, event: RawStateChangeEvent) -> None: ...

    def cleanup(self) -> None: ...
