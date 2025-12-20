from hassette import dependencies as D

# Assuming RedditState is imported or defined
# from .my_states import RedditState


async def on_reddit_change(self, new_state: D.StateNew["RedditState"]):
    print(f"Reddit karma: {new_state.attributes.karma}")
