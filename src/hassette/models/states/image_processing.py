from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ImageProcessingState(StringBaseState):
    """Representation of a Home Assistant image_processing state.

    See: https://www.home-assistant.io/integrations/image_processing/
    """

    class Attributes(AttributesBase):
        faces: list | None = Field(default=None)
        total_faces: int | float | None = Field(default=None)

    domain: Literal["image_processing"]

    attributes: Attributes
