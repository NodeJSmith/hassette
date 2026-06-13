from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import DateTimeState
from hassette.models.states.datetime import DateTimeAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class DateTimeEntity(BaseEntity[DateTimeState, str]):
    @property
    def attributes(self) -> DateTimeAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "DateTimeEntitySyncFacade":
        if self._sync is None:
            self._sync = DateTimeEntitySyncFacade(entity=self)
        return cast("DateTimeEntitySyncFacade", self._sync)

    def set_value(
        self,
        *,
        datetime: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            datetime=datetime,
        )


class DateTimeEntitySyncFacade(BaseEntitySyncFacade[DateTimeState, str]):
    def set_value(
        self,
        *,
        datetime: str,
    ):
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            datetime=datetime,
        )
