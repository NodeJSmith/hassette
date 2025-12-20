from hassette import App


class AllStatesApp(App):
    async def on_initialize(self):
        all_states = self.states.all
        print(f"Total entities: {len(all_states)}")
