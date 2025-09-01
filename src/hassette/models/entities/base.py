import typing
from typing import Generic

from pydantic import BaseModel, ConfigDict, PrivateAttr

from hassette.models.states import StateT

if typing.TYPE_CHECKING:
    from hassette.core.api import Api
    from hassette.core.core import Hassette


class BaseEntity(BaseModel, Generic[StateT]):
    """Base class for all entities."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    state: StateT
    _sync: "BaseEntitySyncFacade[StateT]" = PrivateAttr(default=None, init=False)  # pyright: ignore[reportAssignmentType]

    async def refresh(self) -> StateT:
        self.state = await self.hassette.api.get_state_value_typed(self.entity_id, type(self.state))
        return self.state

    @property
    def value(self) -> str:
        return self.state.value

    @property
    def entity_id(self) -> str:
        return self.state.entity_id

    @property
    def domain(self) -> str:
        return self.state.domain

    @property
    def hassette(self) -> "Hassette":
        """Get the HassAPI instance for this state."""
        from hassette.core.core import Hassette

        return Hassette.get_instance()

    @property
    def api(self) -> "Api":
        """Get the Hassette API instance for this state."""
        return self.hassette.api

    @property
    def sync(self) -> "BaseEntitySyncFacade[StateT]":
        if self._sync is None:
            self._sync = BaseEntitySyncFacade(entity=self)
        return self._sync

    async def turn_off(self):
        """Turn off the entity."""
        return await self.api.turn_off(self.entity_id, self.domain)

    async def turn_on(self, **data):
        """Turn on the entity."""
        return await self.api.turn_on(self.entity_id, self.domain, **data)

    async def toggle(self):
        """Toggle the entity."""
        return await self.api.toggle_service(self.entity_id, self.domain)


class BaseEntitySyncFacade(Generic[StateT]):
    """Synchronous facade for BaseEntity to allow easier access to properties without async/await."""

    entity: BaseEntity[StateT]

    def __init__(self, entity: BaseEntity[StateT]) -> None:
        self.entity = entity

    def turn_off(self):
        """Turn off the entity."""
        return self.entity.api.sync.turn_off(self.entity.entity_id, self.entity.domain)

    def turn_on(self, **data):
        """Turn on the entity."""
        return self.entity.api.sync.turn_on(self.entity.entity_id, self.entity.domain, **data)

    def toggle(self):
        """Toggle the entity."""
        return self.entity.api.sync.toggle_service(self.entity.entity_id, self.entity.domain)
