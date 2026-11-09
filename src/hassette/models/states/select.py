from enum import StrEnum
from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class SelectEntityCapabilityAttribute(StrEnum):
    OPTIONS = "options"


class SelectService(StrEnum):
    SELECT_FIRST = "select_first"
    SELECT_LAST = "select_last"
    SELECT_NEXT = "select_next"
    SELECT_OPTION = "select_option"
    SELECT_PREVIOUS = "select_previous"


class SelectServiceArgument(StrEnum):
    CYCLE = "cycle"
    OPTION = "option"


class SelectAttributes(AttributesBase):
    current_option: str | None = Field(default=None)
    options: list[str] | None = Field(default=None)


class SelectState(StringBaseState):
    """Representation of a Home Assistant select state.

    See: https://www.home-assistant.io/integrations/select/
    """

    domain: Literal["select"]

    attributes: SelectAttributes
