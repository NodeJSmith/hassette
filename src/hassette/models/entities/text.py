from hassette.models.states import TextState
from hassette.models.states.text import TextAttributes

from .base import BaseEntity


class TextEntity(BaseEntity[TextState, str]):
    @property
    def attributes(self) -> TextAttributes:
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
