from collections.abc import Coroutine
from typing import Any

from hassette.models.states import SirenState
from hassette.models.states.siren import SirenAttributes

from .base import BaseEntity


class SirenEntity(BaseEntity[SirenState, str]):
    @property
    def attributes(self) -> SirenAttributes:
        return self.state.attributes

    def turn_on(
        self,
        *,
        duration: str | None = None,
        tone: str | None = None,
        volume_level: float | None = None,
    ) -> Coroutine[Any, Any, None]:
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            duration=duration,
            tone=tone,
            volume_level=volume_level,
        )

    def turn_off(self) -> Coroutine[Any, Any, None]:
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    def toggle(self) -> Coroutine[Any, Any, None]:
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )
