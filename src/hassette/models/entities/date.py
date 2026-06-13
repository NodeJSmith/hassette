from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import DateState
from hassette.models.states.date import DateAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class DateEntity(BaseEntity[DateState, str]):
    @property
    def attributes(self) -> DateAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "DateEntitySyncFacade":
        if self._sync is None:
            self._sync = DateEntitySyncFacade(entity=self)
        return cast("DateEntitySyncFacade", self._sync)

    def set_value(
        self,
        *,
        date: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            date=date,
        )


class DateEntitySyncFacade(BaseEntitySyncFacade[DateState, str]):
    def set_value(
        self,
        *,
        date: str,
    ):
        """Runs synchronously — blocks until the service call completes."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            date=date,
        )
