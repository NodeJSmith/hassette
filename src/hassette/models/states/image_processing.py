from typing import Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class ImageProcessingState(StringBaseState):
    class Attributes(AttributesBase):
        faces: list | None = Field(default=None)
        total_faces: int | float | None = Field(default=None)
        device_class: Literal["face"]

    domain: Literal["image_processing"]

    attributes: Attributes | None = Field(default=None)
