from typing import Annotated

from hassette import A, App, D

from .my_states import RedditState  # pyright: ignore[reportMissingImports]


class MyApp(App):
    async def on_initialize(self):
        self.bus.on_state_change("reddit.my_account", handler=self.on_reddit_change)

    async def on_reddit_change(
        self, new_state: D.StateNew[RedditState], karma: Annotated[int | None, A.get_attr_new("karma")]
    ):
        self.logger.info("New karma: %d", karma or 0)
