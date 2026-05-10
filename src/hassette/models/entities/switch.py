from hassette.models.states import SwitchState
from hassette.models.states.switch import SwitchAttributes

from .base import BaseEntity


class SwitchEntity(BaseEntity[SwitchState, str]):
    @property
    def attributes(self) -> SwitchAttributes:
        return self.state.attributes

    async def turn_on(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )
