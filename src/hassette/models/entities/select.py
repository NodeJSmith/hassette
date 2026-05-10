from hassette.models.states import SelectState
from hassette.models.states.select import SelectAttributes

from .base import BaseEntity


class SelectEntity(BaseEntity[SelectState, str]):
    @property
    def attributes(self) -> SelectAttributes:
        return self.state.attributes

    async def select_first(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_first",
            target={"entity_id": self.entity_id},
        )

    async def select_last(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_last",
            target={"entity_id": self.entity_id},
        )

    async def select_next(
        self,
        *,
        cycle: bool | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_next",
            target={"entity_id": self.entity_id},
            cycle=cycle,
        )

    async def select_option(
        self,
        *,
        option: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_option",
            target={"entity_id": self.entity_id},
            option=option,
        )

    async def select_previous(
        self,
        *,
        cycle: bool | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="select_previous",
            target={"entity_id": self.entity_id},
            cycle=cycle,
        )
