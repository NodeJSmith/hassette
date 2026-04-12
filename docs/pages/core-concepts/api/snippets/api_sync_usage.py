from hassette import App


class SyncApp(App):
    def on_initialize(self):
        # Use .sync to access blocking versions of all async methods
        self.api.sync.turn_on("light.office")
