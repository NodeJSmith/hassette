from hassette.models.states import WaterHeaterState
from hassette.models.states.water_heater import WaterHeaterAttributes

from .base import BaseEntity


class WaterHeaterEntity(BaseEntity[WaterHeaterState, str]):
    @property
    def attributes(self) -> WaterHeaterAttributes:
        return self.state.attributes

    async def set_away_mode(
        self,
        *,
        away_mode: bool,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_away_mode",
            target={"entity_id": self.entity_id},
            away_mode=away_mode,
        )

    async def set_temperature(
        self,
        *,
        temperature: float,
        operation_mode: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_temperature",
            target={"entity_id": self.entity_id},
            temperature=temperature,
            operation_mode=operation_mode,
        )

    async def set_operation_mode(
        self,
        *,
        operation_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_operation_mode",
            target={"entity_id": self.entity_id},
            operation_mode=operation_mode,
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
