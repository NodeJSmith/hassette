from collections.abc import Coroutine
from typing import Any

from hassette.models.states import DateState
from hassette.models.states.date import DateAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class DateEntity(BaseEntity[DateState, str]):
    @property
    def attributes(self) -> DateAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "DateEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(DateEntitySyncFacade)

    def set_value(
        self,
        *,
        date: str,
    ) -> Coroutine[Any, Any, None]:
        """Sets the value of a date.

        Args:
            date: The date to set.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            date=date,
        )


class DateEntitySyncFacade(BaseEntitySyncFacade[DateState, str]):
    """Synchronous facade for DateEntity service methods."""

    def set_value(
        self,
        *,
        date: str,
    ) -> None:
        """Sets the value of a date.

        Args:
            date: The date to set.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set_value",
            target={"entity_id": self.entity.entity_id},
            date=date,
        )
