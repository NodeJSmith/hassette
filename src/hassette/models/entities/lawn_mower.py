from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import LawnMowerState
from hassette.models.states.lawn_mower import LawnMowerAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class LawnMowerEntity(BaseEntity[LawnMowerState, str]):
    @property
    def attributes(self) -> LawnMowerAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "LawnMowerEntitySyncFacade":
        if self._sync is None:
            self._sync = LawnMowerEntitySyncFacade(entity=self)
        return cast("LawnMowerEntitySyncFacade", self._sync)

    def start_mowing(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="start_mowing",
            target={"entity_id": self.entity_id},
        )

    def dock(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="dock",
            target={"entity_id": self.entity_id},
        )

    def pause(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )


class LawnMowerEntitySyncFacade(BaseEntitySyncFacade[LawnMowerState, str]):
    def start_mowing(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="start_mowing",
            target={"entity_id": self.entity.entity_id},
        )

    def dock(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="dock",
            target={"entity_id": self.entity.entity_id},
        )

    def pause(self):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="pause",
            target={"entity_id": self.entity.entity_id},
        )
