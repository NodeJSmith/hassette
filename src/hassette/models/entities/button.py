from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import ButtonState
from hassette.models.states.button import ButtonAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ButtonEntity(BaseEntity[ButtonState, str]):
    @property
    def attributes(self) -> ButtonAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ButtonEntitySyncFacade":
        if self._sync is None:
            self._sync = ButtonEntitySyncFacade(entity=self)
        return cast("ButtonEntitySyncFacade", self._sync)

    def press(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="press",
            target={"entity_id": self.entity_id},
        )


class ButtonEntitySyncFacade(BaseEntitySyncFacade[ButtonState, str]):
    def press(self):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="press",
            target={"entity_id": self.entity.entity_id},
        )
