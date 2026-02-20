from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import LockEntityFeature


class LockAttributes(AttributesBase):
    changed_by: str | None = Field(default=None)
    """Who last changed the lock state."""

    code_format: str | None = Field(default=None)
    """Format of the code required to lock/unlock."""

    @property
    def supports_open(self) -> bool:
        """Whether this lock supports the open action."""
        return self._has_feature(LockEntityFeature.OPEN)


class LockState(StringBaseState):
    """Representation of a Home Assistant lock state.

    See: https://www.home-assistant.io/integrations/lock/
    """

    domain: Literal["lock"]
    attributes: LockAttributes
