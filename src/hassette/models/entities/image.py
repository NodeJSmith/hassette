from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ImageState
from hassette.models.states.image import ImageAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ImageEntity(BaseEntity[ImageState, str]):
    @property
    def attributes(self) -> ImageAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ImageEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(ImageEntitySyncFacade)

    def snapshot(
        self,
        *,
        filename: str,
    ) -> Coroutine[Any, Any, None]:
        """Takes a snapshot from an image.

        Args:
            filename: Template of a filename. Variable available is `entity_id`.
        """
        return self.api.call_service(
            domain=self.domain,
            service="snapshot",
            target={"entity_id": self.entity_id},
            filename=filename,
        )


class ImageEntitySyncFacade(BaseEntitySyncFacade[ImageState, str]):
    """Synchronous facade for ImageEntity service methods."""

    def snapshot(
        self,
        *,
        filename: str,
    ) -> None:
        """Takes a snapshot from an image.

        Args:
            filename: Template of a filename. Variable available is `entity_id`.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="snapshot",
            target={"entity_id": self.entity.entity_id},
            filename=filename,
        )
