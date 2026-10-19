from collections.abc import Coroutine
from typing import Any

from hassette.models.states import AlertState
from hassette.models.states.alert import AlertAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class AlertEntity(BaseEntity[AlertState, str]):
    @property
    def attributes(self) -> AlertAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "AlertEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(AlertEntitySyncFacade)

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles alert's notifications."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Silences alert's notifications."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Resets alert's notifications."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )


class AlertEntitySyncFacade(BaseEntitySyncFacade[AlertState, str]):
    """Synchronous facade for AlertEntity service methods."""

    def toggle(self) -> None:
        """Toggles alert's notifications."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Silences alert's notifications."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_on(self) -> None:
        """Resets alert's notifications."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )
