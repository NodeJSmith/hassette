from hassette.models.states import DateState
from hassette.models.states.date import DateAttributes

from .base import BaseEntity


class DateEntity(BaseEntity[DateState, str]):
    @property
    def attributes(self) -> DateAttributes:
        return self.state.attributes

    async def set_value(
        self,
        *,
        date: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            date=date,
        )
