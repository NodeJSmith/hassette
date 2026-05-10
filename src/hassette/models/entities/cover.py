from hassette.models.states import CoverState
from hassette.models.states.cover import CoverAttributes

from .base import BaseEntity


class CoverEntity(BaseEntity[CoverState, str]):
    @property
    def attributes(self) -> CoverAttributes:
        return self.state.attributes

    async def open_cover(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="open_cover",
            target={"entity_id": self.entity_id},
        )

    async def close_cover(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="close_cover",
            target={"entity_id": self.entity_id},
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    async def set_cover_position(
        self,
        *,
        position: int,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_cover_position",
            target={"entity_id": self.entity_id},
            position=position,
        )

    async def stop_cover(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="stop_cover",
            target={"entity_id": self.entity_id},
        )

    async def open_cover_tilt(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="open_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    async def close_cover_tilt(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="close_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    async def toggle_cover_tilt(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle_cover_tilt",
            target={"entity_id": self.entity_id},
        )

    async def set_cover_tilt_position(
        self,
        *,
        tilt_position: int,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_cover_tilt_position",
            target={"entity_id": self.entity_id},
            tilt_position=tilt_position,
        )

    async def stop_cover_tilt(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="stop_cover_tilt",
            target={"entity_id": self.entity_id},
        )
