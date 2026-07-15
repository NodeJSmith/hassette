from collections.abc import Coroutine
from typing import Any

from hassette.models.states import SwitchState
from hassette.models.states.switch import SwitchAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class SwitchEntity(BaseEntity[SwitchState, str]):
    @property
    def attributes(self) -> SwitchAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "SwitchEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(SwitchEntitySyncFacade)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Turns on a switch."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turns off a switch."""
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggles a switch on/off."""
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class SwitchEntitySyncFacade(BaseEntitySyncFacade[SwitchState, str]):
    """Synchronous facade for SwitchEntity service methods."""

    def turn_on(self) -> None:
        """Turns on a switch."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Turns off a switch."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Toggles a switch on/off."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
