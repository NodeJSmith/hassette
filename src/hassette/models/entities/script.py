from hassette.models.states import ScriptState
from hassette.models.states.script import ScriptAttributes

from .base import BaseEntity


class ScriptEntity(BaseEntity[ScriptState, str]):
    @property
    def attributes(self) -> ScriptAttributes:
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
