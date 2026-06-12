from collections.abc import Coroutine
from typing import Any

from hassette.models.states import NumberState
from hassette.models.states.number import NumberAttributes

from .base import BaseEntity


class NumberEntity(BaseEntity[NumberState, str]):
    @property
    def attributes(self) -> NumberAttributes:
        return self.state.attributes

    def set_value(
        self,
        *,
        value: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` emits ``HassetteForgottenAwaitWarning``."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            value=value,
        )
