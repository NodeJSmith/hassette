from hassette import App

from .my_states import RedditState  # pyright: ignore[reportMissingImports]


class MyApp(App):
    async def on_initialize(self):
        reddit_state = await self.api.get_state("reddit.my_account")
        assert isinstance(reddit_state, RedditState)
        if reddit_state.attributes.subreddit:
            print(f"Subreddit: {reddit_state.attributes.subreddit}")
