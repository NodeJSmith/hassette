from hassette import App


class MyApp(App):
    async def on_initialize(self):
        # Works at runtime but static analysis sees BaseState
        for entity_id, state in self.states.my_custom_domain:
            print(state.value)  # state is typed as BaseState
