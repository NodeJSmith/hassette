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
        value: float,
    ) -> Coroutine[Any, Any, None]:
        """Sets the value of a number.

        Args:
            value: The target value to set.
        """
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
        value: float,
    ) -> None:
        """Sets the value of a number.

        Args:
            value: The target value to set.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            value=value,
        )
