from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TimeState
from hassette.models.states.time import TimeAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class TimeEntity(BaseEntity[TimeState, str]):
    @property
    def attributes(self) -> TimeAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TimeEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(TimeEntitySyncFacade)

    def set_value(
        self,
        *,
        time: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the value of a time entity.

        Args:
            time: The time to set.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            time=time,
        )


class TimeEntitySyncFacade(BaseEntitySyncFacade[TimeState, str]):
    """Synchronous facade for TimeEntity service methods."""

    def set_value(
        self,
        *,
        time: str,
    ) -> None:
        """Sets the value of a time entity.

        Args:
            time: The time to set.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            time=time,
        )
