from typing import Literal

from hassette.models.states import CameraState
from hassette.models.states.camera import CameraAttributes

from .base import BaseEntity

Format = Literal["hls"]


class CameraEntity(BaseEntity[CameraState, str]):
    @property
    def attributes(self) -> CameraAttributes:
        return self.state.attributes

    async def turn_off(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
        )

    async def turn_on(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    async def enable_motion_detection(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="enable_motion_detection",
            target={"entity_id": self.entity_id},
        )

    async def disable_motion_detection(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="disable_motion_detection",
            target={"entity_id": self.entity_id},
        )

    async def snapshot(
        self,
        *,
        filename: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="snapshot",
            target={"entity_id": self.entity_id},
            filename=filename,
        )

    async def play_stream(
        self,
        *,
        media_player: str,
        format: Format | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="play_stream",
            target={"entity_id": self.entity_id},
            media_player=media_player,
            format=format,
        )

    async def record(
        self,
        *,
        filename: str,
        duration: int | None = None,
        lookback: int | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="record",
            target={"entity_id": self.entity_id},
            filename=filename,
            duration=duration,
            lookback=lookback,
        )
