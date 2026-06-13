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
        """Call the image.snapshot service.

        Args:
            filename: Template of a filename. Variable available is `entity_id`.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
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
        """Call the image.snapshot service synchronously.

        Args:
            filename: Template of a filename. Variable available is `entity_id`.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="snapshot",
            target={"entity_id": self.entity.entity_id},
            filename=filename,
        )
