from typing import ClassVar

from pydantic import BaseModel

from hassette.models.states import BaseState


class RedditAttributes(BaseModel):
    karma: int | None = None
    subreddit: str | None = None
    friendly_name: str | None = None


class RedditState(BaseState):
    """State model for custom reddit sensor."""

    domain: ClassVar[str] = "reddit"
    attributes: RedditAttributes
