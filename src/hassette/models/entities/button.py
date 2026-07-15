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
        """Presses a button."""
        return self.api.call_service(
            domain=self.domain,
            service="press",
            target={"entity_id": self.entity_id},
        )


class ButtonEntitySyncFacade(BaseEntitySyncFacade[ButtonState, str]):
    """Synchronous facade for ButtonEntity service methods."""

    def press(self) -> None:
        """Presses a button."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="press",
            target={"entity_id": self.entity.entity_id},
        )
