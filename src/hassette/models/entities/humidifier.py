from hassette.models.states import HumidifierState
from hassette.models.states.humidifier import HumidifierAttributes

from .base import BaseEntity


class HumidifierEntity(BaseEntity[HumidifierState, str]):
    @property
    def attributes(self) -> HumidifierAttributes:
        return self.state.attributes

    async def set_mode(
        self,
        *,
        mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_mode",
            target={"entity_id": self.entity_id},
            mode=mode,
        )

    async def set_humidity(
        self,
        *,
        humidity: int,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_humidity",
            target={"entity_id": self.entity_id},
            humidity=humidity,
        )

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
