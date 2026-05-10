from typing import Literal

from hassette.models.states import FanState
from hassette.models.states.fan import FanAttributes

from .base import BaseEntity

Direction = Literal["forward", "reverse"]


class FanEntity(BaseEntity[FanState, str]):
    @property
    def attributes(self) -> FanAttributes:
        return self.state.attributes

    async def set_preset_mode(
        self,
        *,
        preset_mode: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_preset_mode",
            target={"entity_id": self.entity_id},
            preset_mode=preset_mode,
        )

    async def set_percentage(
        self,
        *,
        percentage: int,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_percentage",
            target={"entity_id": self.entity_id},
            percentage=percentage,
        )

    async def turn_on(
        self,
        *,
        percentage: int | None = None,
        preset_mode: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            percentage=percentage,
            preset_mode=preset_mode,
        )

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def oscillate(
        self,
        *,
        oscillating: bool,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="oscillate",
            target={"entity_id": self.entity_id},
            oscillating=oscillating,
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    async def set_direction(
        self,
        *,
        direction: Direction,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_direction",
            target={"entity_id": self.entity_id},
            direction=direction,
        )

    async def increase_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="increase_speed",
            target={"entity_id": self.entity_id},
            percentage_step=percentage_step,
        )

    async def decrease_speed(
        self,
        *,
        percentage_step: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="decrease_speed",
            target={"entity_id": self.entity_id},
            percentage_step=percentage_step,
        )
