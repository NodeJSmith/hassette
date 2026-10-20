from collections.abc import Coroutine
from typing import Any

from hassette.models.services import ServiceResponse
from hassette.models.states import ScheduleState
from hassette.models.states.schedule import ScheduleAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class ScheduleEntity(BaseEntity[ScheduleState, str]):
    @property
    def attributes(self) -> ScheduleAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "ScheduleEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(ScheduleEntitySyncFacade)

    def get_schedule(self) -> Coroutine[Any, Any, ServiceResponse]:
        """Retrieves the configured time ranges of one or multiple schedules."""
        return self.api.call_service(
            domain=self.domain,
            service="get_schedule",
            target={"entity_id": self.entity_id},
            return_response=True,
        )


class ScheduleEntitySyncFacade(BaseEntitySyncFacade[ScheduleState, str]):
    """Synchronous facade for ScheduleEntity service methods."""

    def get_schedule(self) -> ServiceResponse | None:
        """Retrieves the configured time ranges of one or multiple schedules."""
        return self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="get_schedule",
            target={"entity_id": self.entity.entity_id},
            return_response=True,
        )
