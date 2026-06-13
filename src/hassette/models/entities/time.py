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
        """Call the time.set_value service.

        Args:
            time: The time to set.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
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
        """Call the time.set_value service synchronously.

        Args:
            time: The time to set.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            time=time,
        )
