from hassette.models.states import NumberState
from hassette.models.states.number import NumberAttributes

from .base import BaseEntity


class NumberEntity(BaseEntity[NumberState, str]):
    @property
    def attributes(self) -> NumberAttributes:
        return self.state.attributes

    async def set_value(
        self,
        *,
        value: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="set_value",
            target={"entity_id": self.entity_id},
            value=value,
        )
