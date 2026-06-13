from collections.abc import Coroutine
from typing import Any, cast

from hassette.models.states import TextState
from hassette.models.states.text import TextAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TextEntity(BaseEntity[TextState, str]):
    @property
    def attributes(self) -> TextAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TextEntitySyncFacade":
        if self._sync is None:
            self._sync = TextEntitySyncFacade(entity=self)
        return cast("TextEntitySyncFacade", self._sync)

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


class TextEntitySyncFacade(BaseEntitySyncFacade[TextState, str]):
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
