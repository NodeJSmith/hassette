from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ButtonState
from hassette.models.states.button import ButtonAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ButtonEntity(BaseEntity[ButtonState, str]):
    @property
    def attributes(self) -> ButtonAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ButtonEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(ButtonEntitySyncFacade)

    def press(self) -> Coroutine[Any, Any, None]:
        """Call the button.press service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="press",
            target={"entity_id": self.entity_id},
        )


class ButtonEntitySyncFacade(BaseEntitySyncFacade[ButtonState, str]):
    """Synchronous facade for ButtonEntity service methods."""

    def press(self) -> None:
        """Call the button.press service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="press",
            target={"entity_id": self.entity.entity_id},
        )
