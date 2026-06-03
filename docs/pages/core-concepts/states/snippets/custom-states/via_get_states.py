from hassette import App

from .my_states import RedditState  # pyright: ignore[reportMissingImports]


class MyApp(App):
    async def on_initialize(self):
        # Get all reddit entities
        reddit_states = self.states[RedditState]

        for entity_id, state in reddit_states:
            print(f"{entity_id}: {state.value}")
            if state.attributes.karma:
                print(f"  Karma: {state.attributes.karma}")
