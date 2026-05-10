from hassette.models.states import ButtonState
from hassette.models.states.button import ButtonAttributes

from .base import BaseEntity


class ButtonEntity(BaseEntity[ButtonState, str]):
    @property
    def attributes(self) -> ButtonAttributes:
        return self.state.attributes

    async def press(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="press",
            target={"entity_id": self.entity_id},
        )
