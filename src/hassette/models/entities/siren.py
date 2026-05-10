from hassette.models.states import SirenState
from hassette.models.states.siren import SirenAttributes

from .base import BaseEntity


class SirenEntity(BaseEntity[SirenState, str]):
    @property
    def attributes(self) -> SirenAttributes:
        return self.state.attributes

    async def turn_on(
        self,
        *,
        duration: str | None = None,
        tone: str | None = None,
        volume_level: float | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
            duration=duration,
            tone=tone,
            volume_level=volume_level,
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
