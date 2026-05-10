from hassette.models.states import AutomationState
from hassette.models.states.automation import AutomationAttributes

from .base import BaseEntity


class AutomationEntity(BaseEntity[AutomationState, str]):
    @property
    def attributes(self) -> AutomationAttributes:
        return self.state.attributes

    async def turn_on(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_on",
            target={"entity_id": self.entity_id},
        )

    async def turn_off(
        self,
        *,
        stop_actions: bool | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="turn_off",
            target={"entity_id": self.entity_id},
            stop_actions=stop_actions,
        )

    async def toggle(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="toggle",
            target={"entity_id": self.entity_id},
        )

    async def trigger(
        self,
        *,
        skip_condition: bool | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="trigger",
            target={"entity_id": self.entity_id},
            skip_condition=skip_condition,
        )
