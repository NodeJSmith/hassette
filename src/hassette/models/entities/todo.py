from typing import Literal

from hassette.models.states import TodoState
from hassette.models.states.todo import TodoAttributes

from .base import BaseEntity

Status = Literal["needs_action", "completed"]


class TodoEntity(BaseEntity[TodoState, str]):
    @property
    def attributes(self) -> TodoAttributes:
        return self.state.attributes

    async def get_items(
        self,
        *,
        status: Status | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="get_items",
            target={"entity_id": self.entity_id},
            status=status,
        )

    async def add_item(
        self,
        *,
        item: str,
        description: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="add_item",
            target={"entity_id": self.entity_id},
            item=item,
            description=description,
            due_date=due_date,
            due_datetime=due_datetime,
        )

    async def update_item(
        self,
        *,
        item: str,
        description: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
        rename: str | None = None,
        status: Literal["needs_action", "completed"] | None = None,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="update_item",
            target={"entity_id": self.entity_id},
            item=item,
            description=description,
            due_date=due_date,
            due_datetime=due_datetime,
            rename=rename,
            status=status,
        )

    async def remove_item(
        self,
        *,
        item: str,
    ) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="remove_item",
            target={"entity_id": self.entity_id},
            item=item,
        )

    async def remove_completed_items(self) -> None:
        await self.api.call_service(
            domain=self.domain,
            service="remove_completed_items",
            target={"entity_id": self.entity_id},
        )
