# my_states.py
from typing import Literal

from pydantic import Field

from hassette.models.states.base import AttributesBase, StringBaseState


class ImageAttributes(AttributesBase):
    """Attributes for image entities."""

    url: str | None = Field(default=None)
    width: int | None = Field(default=None)
    height: int | None = Field(default=None)
    content_type: str | None = Field(default=None)


class ImageState(StringBaseState):
    """State class for image domain."""

    domain: Literal["image"]
    attributes: ImageAttributes


# my_app.py
from hassette import App
from hassette import dependencies as D


class ImageMonitorApp(App):
    async def on_initialize(self):
        # Monitor all image entities
        self.bus.on_state_change(
            entity_id="image.*",
            handler=self.on_image_change,  # Glob pattern
        )

    async def on_image_change(
        self,
        new_state: D.StateNew[ImageState],
        entity_id: D.EntityId,
    ):
        attrs = new_state.attributes
        self.logger.info(
            "Image %s updated: %dx%d, %s",
            entity_id,
            attrs.width or 0,
            attrs.height or 0,
            attrs.content_type or "unknown",
        )
