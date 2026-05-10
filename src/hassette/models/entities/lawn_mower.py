from hassette.models.states import LawnMowerState
from hassette.models.states.lawn_mower import LawnMowerAttributes

from .base import BaseEntity


class LawnMowerEntity(BaseEntity[LawnMowerState, str]):
    @property
    def attributes(self) -> LawnMowerAttributes:
        return self.state.attributes

    async def start_mowing(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="start_mowing",
            target={"entity_id": self.entity_id},
        )

    async def dock(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="dock",
            target={"entity_id": self.entity_id},
        )

    async def pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )
