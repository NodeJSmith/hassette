from hassette.models.states import DateTimeState
from hassette.models.states.datetime import DateTimeAttributes

from .base import BaseEntity


class DateTimeEntity(BaseEntity[DateTimeState, str]):
    @property
    def attributes(self) -> DateTimeAttributes:
        return self.state.attributes

    async def set_value(
        self,
        *,
        datetime: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            datetime=datetime,
        )
