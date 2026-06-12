from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TextState
from hassette.models.states.text import TextAttributes

from .base import BaseEntity


class TextEntity(BaseEntity[TextState, str]):
    @property
    def attributes(self) -> TextAttributes:
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
