from collections.abc import Coroutine
from typing import Any

from hassette.models.states import LawnMowerState
from hassette.models.states.lawn_mower import LawnMowerAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class LawnMowerEntity(BaseEntity[LawnMowerState, str]):
    @property
    def attributes(self) -> LawnMowerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "LawnMowerEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(LawnMowerEntitySyncFacade)

    def start_mowing(self) -> Coroutine[Any, Any, None]:
        """Call the lawn_mower.start_mowing service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start_mowing",
            target={"entity_id": self.entity_id},
        )

    def dock(self) -> Coroutine[Any, Any, None]:
        """Call the lawn_mower.dock service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="dock",
            target={"entity_id": self.entity_id},
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Call the lawn_mower.pause service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )


class LawnMowerEntitySyncFacade(BaseEntitySyncFacade[LawnMowerState, str]):
    """Synchronous facade for LawnMowerEntity service methods."""

    def start_mowing(self) -> None:
        """Call the lawn_mower.start_mowing service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start_mowing",
            target={"entity_id": self.entity.entity_id},
        )

    def dock(self) -> None:
        """Call the lawn_mower.dock service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="dock",
            target={"entity_id": self.entity.entity_id},
        )

    def pause(self) -> None:
        """Call the lawn_mower.pause service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )
