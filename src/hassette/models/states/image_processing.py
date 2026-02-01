from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ImageProcessingAttributes(AttributesBase):
    faces: list | None = Field(default=None)
    total_faces: int | float | None = Field(default=None)


class ImageProcessingState(StringBaseState):
    """Representation of a Home Assistant image_processing state.

    See: https://www.home-assistant.io/integrations/image_processing/
    """

    domain: Literal["image_processing"]

    attributes: ImageProcessingAttributes
