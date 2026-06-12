from collections.abc import Coroutine
from typing import Any

from hassette.models.states import ButtonState
from hassette.models.states.button import ButtonAttributes

from .base import BaseEntity


class ButtonEntity(BaseEntity[ButtonState, str]):
    @property
    def attributes(self) -> ButtonAttributes:
        return self.state.attributes

    def press(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` emits ``HassetteForgottenAwaitWarning``."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="press",
            target={"entity_id": self.entity_id},
        )
