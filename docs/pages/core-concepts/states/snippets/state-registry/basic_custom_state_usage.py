from hassette import App, D

from .my_states import RedditState


class MyApp(App):
    async def on_initialize(self):
        await self.bus.on_state_change("reddit.my_account", handler=self.on_reddit_change, name="reddit_account")

    async def on_reddit_change(self, new_state: D.StateNew[RedditState]):
        self.logger.info("New karma: %s", new_state.attributes.karma)
