from hassette import AppSync


class SyncApp(AppSync):
    def on_initialize_sync(self):
        # Use .sync to access blocking versions of all async methods
        self.api.sync.turn_on("light.office")
