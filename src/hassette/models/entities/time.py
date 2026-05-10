from hassette.models.states import TimeState
from hassette.models.states.time import TimeAttributes

from .base import BaseEntity


class TimeEntity(BaseEntity[TimeState, str]):
    @property
    def attributes(self) -> TimeAttributes:
        return self.state.attributes

    async def set_value(
        self,
        *,
        time: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            time=time,
        )
