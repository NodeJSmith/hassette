from hassette import App


class SyncFacadeExample(App):
    def sync_example(self):
        # Inside an AppSync or non-async context
        self.api.sync.turn_off("light.bedroom", domain="light")
