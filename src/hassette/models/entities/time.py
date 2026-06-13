from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import TimeState
from hassette.models.states.time import TimeAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TimeEntity(BaseEntity[TimeState, str]):
    @property
    def attributes(self) -> TimeAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TimeEntitySyncFacade":
        if self._sync is None:
            self._sync = TimeEntitySyncFacade(entity=self)
        return cast("TimeEntitySyncFacade", self._sync)

    def set_value(
        self,
        *,
        time: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            time=time,
        )


class TimeEntitySyncFacade(BaseEntitySyncFacade[TimeState, str]):
    def set_value(
        self,
        *,
        time: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            time=time,
        )
