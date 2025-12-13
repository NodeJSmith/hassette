from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class RemoteState(StringBaseState):
    """Representation of a Home Assistant remote state.

    See: https://www.home-assistant.io/integrations/remote/
    """

    class Attributes(AttributesBase):
        activity_list: list | None = Field(default=None)
        current_activity: str | None = Field(default=None)

    domain: Literal["remote"]

    attributes: Attributes
