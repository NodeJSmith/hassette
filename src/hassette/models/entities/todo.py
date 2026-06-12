from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import TodoState
from hassette.models.states.todo import TodoAttributes

from .base import BaseEntity

Status = Literal["needs_action", "completed"]


class TodoEntity(BaseEntity[TodoState, str]):
    @property
    def attributes(self) -> TodoAttributes:
        return self.state.attributes

    def get_items(
        self,
        *,
        status: Status | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="get_items",
            target={"entity_id": self.entity_id},
            status=status,
        )

    def add_item(
        self,
        *,
        item: str,
        description: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="add_item",
            target={"entity_id": self.entity_id},
            item=item,
            description=description,
            due_date=due_date,
            due_datetime=due_datetime,
        )

    def update_item(
        self,
        *,
        item: str,
        description: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
        rename: str | None = None,
        status: Literal["needs_action", "completed"] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
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

    def remove_item(
        self,
        *,
        item: str,
    ) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="remove_item",
            target={"entity_id": self.entity_id},
            item=item,
        )

    def remove_completed_items(self) -> Coroutine[Any, Any, None]:
        """Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn)."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="remove_completed_items",
            target={"entity_id": self.entity_id},
        )
