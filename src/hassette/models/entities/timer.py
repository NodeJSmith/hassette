from hassette.models.states import TimerState
from hassette.models.states.timer import TimerAttributes

from .base import BaseEntity


class TimerEntity(BaseEntity[TimerState, str]):
    @property
    def attributes(self) -> TimerAttributes:
        return self.state.attributes

    async def start(
        self,
        *,
        duration: dict[str, int] | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="start",
            target={"entity_id": self.entity_id},
            duration=duration,
        )

    async def pause(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="pause",
            target={"entity_id": self.entity_id},
        )

    async def cancel(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="cancel",
            target={"entity_id": self.entity_id},
        )

    async def finish(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="finish",
            target={"entity_id": self.entity_id},
        )

    async def change(
        self,
        *,
        duration: dict[str, int],
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="change",
            target={"entity_id": self.entity_id},
            duration=duration,
        )
