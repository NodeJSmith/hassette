from collections.abc import Coroutine
from typing import Any

from hassette.models.states import DateTimeState
from hassette.models.states.datetime import DateTimeAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class DateTimeEntity(BaseEntity[DateTimeState, str]):
    @property
    def attributes(self) -> DateTimeAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "DateTimeEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(DateTimeEntitySyncFacade)

    def set_value(
        self,
        *,
        datetime: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the value of a date/time.

        Args:
            datetime: The date/time to set. The time zone of the Home Assistant instance is assumed.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            datetime=datetime,
        )


class DateTimeEntitySyncFacade(BaseEntitySyncFacade[DateTimeState, str]):
    """Synchronous facade for DateTimeEntity service methods."""

    def set_value(
        self,
        *,
        datetime: str,
    ) -> None:
        """Sets the value of a date/time.

        Args:
            datetime: The date/time to set. The time zone of the Home Assistant instance is assumed.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            datetime=datetime,
        )
