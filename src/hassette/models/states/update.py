from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, StringBaseState


class UpdateState(StringBaseState):
    class Attributes(AttributesBase):
        auto_update: bool | None = Field(default=None)
        display_precision: int | float | None = Field(default=None)
        installed_version: str | None = Field(default=None)
        in_progress: bool | None = Field(default=None)
        latest_version: str | None = Field(default=None)
        release_summary: Any | None = Field(default=None)
        release_url: str | None = Field(default=None)
        skipped_version: Any | None = Field(default=None)
        title: str | None = Field(default=None)
        update_percentage: Any | None = Field(default=None)
        entity_picture: str | None = Field(default=None)

    domain: Literal["update"]

    attributes: Attributes
