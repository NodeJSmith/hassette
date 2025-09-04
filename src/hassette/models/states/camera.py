from typing import Literal

from pydantic import Field, SecretStr

from .base import AttributesBase, StringBaseState


class CameraState(StringBaseState):
    class Attributes(AttributesBase):
        access_token: SecretStr | None = Field(default=None)
        model_name: str | None = Field(default=None)
        brand: str | None = Field(default=None)
        entity_picture: str | None = Field(default=None)

    domain: Literal["camera"]

    attributes: Attributes
