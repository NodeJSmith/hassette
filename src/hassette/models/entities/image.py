from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ImageState
from hassette.models.states.image import ImageAttributes

from .base import BaseEntity


class ImageEntity(BaseEntity[ImageState, str]):
    @property
    def attributes(self) -> ImageAttributes:
        return self.state.attributes

    def snapshot(
        self,
        *,
        filename: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="snapshot",
            target={"entity_id": self.entity_id},
            filename=filename,
        )
