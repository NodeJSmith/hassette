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
        """Call the switch.turn_on service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Call the switch.turn_off service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Call the switch.toggle service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class SwitchEntitySyncFacade(BaseEntitySyncFacade[SwitchState, str]):
    """Synchronous facade for SwitchEntity service methods."""

    def turn_on(self) -> None:
        """Call the switch.turn_on service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self) -> None:
        """Call the switch.turn_off service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self) -> None:
        """Call the switch.toggle service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
