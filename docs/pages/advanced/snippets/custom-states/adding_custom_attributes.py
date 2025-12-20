from typing import Literal

from pydantic import Field

from hassette.models.states.base import AttributesBase, StringBaseState


class RedditAttributes(AttributesBase):
    """Attributes for Reddit entities."""

    subreddit: str | None = Field(default=None)
    post_count: int | None = Field(default=None)
    karma: int | None = Field(default=None)


class RedditState(StringBaseState):
    """State class for reddit domain entities."""

    domain: Literal["reddit"]
    attributes: RedditAttributes  # Override attributes type
