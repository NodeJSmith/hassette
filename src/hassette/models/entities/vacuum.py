from typing import Any

from hassette.models.states import VacuumState
from hassette.models.states.vacuum import VacuumAttributes

from .base import BaseEntity


class VacuumEntity(BaseEntity[VacuumState, str]):
    @property
    def attributes(self) -> VacuumAttributes:
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

    async def stop(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="stop",
            target={"entity_id": self.entity_id},
        )

    async def locate(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="locate",
            target={"entity_id": self.entity_id},
        )

    async def start_pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="start_pause",
            target={"entity_id": self.entity_id},
        )

    async def start(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
        )

    async def pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    async def return_to_base(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="return_to_base",
            target={"entity_id": self.entity_id},
        )

    async def clean_spot(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="clean_spot",
            target={"entity_id": self.entity_id},
        )

    async def clean_area(
        self,
        *,
        cleaning_area_id: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="clean_area",
            target={"entity_id": self.entity_id},
            cleaning_area_id=cleaning_area_id,
        )

    async def send_command(
        self,
        *,
        command: str,
        params: Any | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="send_command",
            target={"entity_id": self.entity_id},
            command=command,
            params=params,
        )

    async def set_fan_speed(
        self,
        *,
        fan_speed: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_fan_speed",
            target={"entity_id": self.entity_id},
            fan_speed=fan_speed,
        )
