from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import NumberState
from hassette.models.states.number import NumberAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class NumberEntity(BaseEntity[NumberState, str]):
    @property
    def attributes(self) -> NumberAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "NumberEntitySyncFacade":
        if self._sync is None:
            self._sync = NumberEntitySyncFacade(entity=self)
        return cast("NumberEntitySyncFacade", self._sync)

    def set_value(
        self,
        *,
        value: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            value=value,
        )


class NumberEntitySyncFacade(BaseEntitySyncFacade[NumberState, str]):
    def set_value(
        self,
        *,
        value: str,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            value=value,
        )
