from hassette import AppSync


class MyApp(AppSync):
    def on_initialize_sync(self) -> None:
        self.api.sync.call_service("light", "turn_on", target={"entity_id": "light.kitchen"})
