from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState
from .features import CoverEntityFeature


class CoverAttributes(AttributesBase):
    current_position: int | None = Field(default=None)
    """Current position of the cover (0 = closed, 100 = open)."""

    current_tilt_position: int | None = Field(default=None)
    """Current tilt position of the cover (0 = closed, 100 = open)."""

    @property
    def supports_open(self) -> bool:
        """Whether this cover supports opening."""
        return self._has_feature(CoverEntityFeature.OPEN)

    @property
    def supports_close(self) -> bool:
        """Whether this cover supports closing."""
        return self._has_feature(CoverEntityFeature.CLOSE)

    @property
    def supports_set_position(self) -> bool:
        """Whether this cover supports setting position."""
        return self._has_feature(CoverEntityFeature.SET_POSITION)

    @property
    def supports_stop(self) -> bool:
        """Whether this cover supports stopping."""
        return self._has_feature(CoverEntityFeature.STOP)

    @property
    def supports_open_tilt(self) -> bool:
        """Whether this cover supports opening tilt."""
        return self._has_feature(CoverEntityFeature.OPEN_TILT)

    @property
    def supports_close_tilt(self) -> bool:
        """Whether this cover supports closing tilt."""
        return self._has_feature(CoverEntityFeature.CLOSE_TILT)

    @property
    def supports_stop_tilt(self) -> bool:
        """Whether this cover supports stopping tilt."""
        return self._has_feature(CoverEntityFeature.STOP_TILT)

    @property
    def supports_set_tilt_position(self) -> bool:
        """Whether this cover supports setting tilt position."""
        return self._has_feature(CoverEntityFeature.SET_TILT_POSITION)


class CoverState(StringBaseState):
    """Representation of a Home Assistant cover state.

    See: https://www.home-assistant.io/integrations/cover/
    """

    domain: Literal["cover"]

    attributes: CoverAttributes
