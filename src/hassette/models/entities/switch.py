from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import SwitchState
from hassette.models.states.switch import SwitchAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class SwitchEntity(BaseEntity[SwitchState, str]):
    @property
    def attributes(self) -> SwitchAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "SwitchEntitySyncFacade":
        if self._sync is None:
            self._sync = SwitchEntitySyncFacade(entity=self)
        return cast("SwitchEntitySyncFacade", self._sync)

    def turn_on(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )


class SwitchEntitySyncFacade(BaseEntitySyncFacade[SwitchState, str]):
    def turn_on(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_on",
            target={"entity_id": self.entity.entity_id},
        )

    def turn_off(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="turn_off",
            target={"entity_id": self.entity.entity_id},
        )

    def toggle(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="toggle",
            target={"entity_id": self.entity.entity_id},
        )
