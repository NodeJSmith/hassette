from collections.abc import Coroutine
from typing import Any, Literal

from hassette.models.states import TodoState
from hassette.models.states.todo import TodoAttributes

from .base import BaseEntity, BaseEntitySyncFacade

Status = Literal["needs_action", "completed"]


class TodoEntity(BaseEntity[TodoState, str]):
    @property
    def attributes(self) -> TodoAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "TodoEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(TodoEntitySyncFacade)

    def get_items(
        self,
        *,
        status: Status | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Call the todo.get_items service.

        Args:
            status: Only return to-do items with the specified statuses. Returns not completed actions by default.
        """
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
        """Call the todo.add_item service.

        Args:
            item: The name that represents the to-do item.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
        """
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
        """Call the todo.update_item service.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
            rename: The new name for the to-do item.
            status: A status or confirmation of the to-do item.
        """
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
        """Call the todo.remove_item service.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="remove_item",
            target={"entity_id": self.entity_id},
            item=item,
        )

    def remove_completed_items(self) -> Coroutine[Any, Any, None]:
        """Call the todo.remove_completed_items service."""
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.call_service(
            domain=self.domain,
            service="remove_completed_items",
            target={"entity_id": self.entity_id},
        )


class TodoEntitySyncFacade(BaseEntitySyncFacade[TodoState, str]):
    """Synchronous facade for TodoEntity service methods."""

    def get_items(
        self,
        *,
        status: Status | None = None,
    ) -> None:
        """Call the todo.get_items service synchronously.

        Args:
            status: Only return to-do items with the specified statuses. Returns not completed actions by default.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="get_items",
            target={"entity_id": self.entity.entity_id},
            status=status,
        )

    def add_item(
        self,
        *,
        item: str,
        description: str | None = None,
        due_date: str | None = None,
        due_datetime: str | None = None,
    ) -> None:
        """Call the todo.add_item service synchronously.

        Args:
            item: The name that represents the to-do item.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="add_item",
            target={"entity_id": self.entity.entity_id},
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
    ) -> None:
        """Call the todo.update_item service synchronously.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
            rename: The new name for the to-do item.
            status: A status or confirmation of the to-do item.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="update_item",
            target={"entity_id": self.entity.entity_id},
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
    ) -> None:
        """Call the todo.remove_item service synchronously.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="remove_item",
            target={"entity_id": self.entity.entity_id},
            item=item,
        )

    def remove_completed_items(self) -> None:
        """Call the todo.remove_completed_items service synchronously.

        Returns:
            None.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="remove_completed_items",
            target={"entity_id": self.entity.entity_id},
        )
