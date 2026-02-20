from typing import Literal

from pydantic import Field, SecretStr

from .base import AttributesBase, StringBaseState


class CameraAttributes(AttributesBase):
    access_token: SecretStr | None = Field(default=None)
    model_name: str | None = Field(default=None)
    brand: str | None = Field(default=None)
    entity_picture: str | None = Field(default=None)

    motion_detection: bool | None = Field(default=None)
    """Whether motion detection is enabled."""


class CameraState(StringBaseState):
    """Representation of a Home Assistant camera state.

    See: https://www.home-assistant.io/integrations/camera/
    """

    domain: Literal["camera"]

    attributes: CameraAttributes
