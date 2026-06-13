from collections.abc import Coroutine
from typing import Any

from hassette.models.states import NumberState
from hassette.models.states.number import NumberAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class NumberEntity(BaseEntity[NumberState, str]):
    @property
    def attributes(self) -> NumberAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "NumberEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(NumberEntitySyncFacade)

    def set_value(
        self,
        *,
        value: str,
    ) -> Coroutine[Any, Any, None]:
        """Call the number.set_value service.

        Args:
            value: The target value to set.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            value=value,
        )


class NumberEntitySyncFacade(BaseEntitySyncFacade[NumberState, str]):
    """Synchronous facade for NumberEntity service methods."""

    def set_value(
        self,
        *,
        value: str,
    ) -> None:
        """Call the number.set_value service synchronously.

        Args:
            value: The target value to set.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            value=value,
        )
