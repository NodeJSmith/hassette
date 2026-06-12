from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TimeState
from hassette.models.states.time import TimeAttributes

from .base import BaseEntity


class TimeEntity(BaseEntity[TimeState, str]):
    @property
    def attributes(self) -> TimeAttributes:
        return self.state.attributes

    def set_value(
        self,
        *,
        time: str,
    ) -> Coroutine[Any, Any, None]:
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            time=time,
        )
