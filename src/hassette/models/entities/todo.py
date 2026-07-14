from collections.abc import Coroutine
from typing import Any

from hassette.models.states import TodoState
from hassette.models.states.todo import TodoAttributes, TodoItemStatus

from .base import BaseEntity, BaseEntitySyncFacade


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
        status: list[TodoItemStatus] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Gets items on a to-do list.

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
        """Adds a new to-do list item.

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
        status: TodoItemStatus | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Updates an existing to-do list item based on its name or UID.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
            rename: The new name for the to-do item.
            status: A status for the to-do item.
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
        """Removes an existing to-do list item by its name or UID.

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
        """Removes all to-do list items that have been completed."""
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
        status: list[TodoItemStatus] | None = None,
    ) -> None:
        """Gets items on a to-do list.

        Args:
            status: Only return to-do items with the specified statuses. Returns not completed actions by default.
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
        """Adds a new to-do list item.

        Args:
            item: The name that represents the to-do item.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
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
        status: TodoItemStatus | None = None,
    ) -> None:
        """Updates an existing to-do list item based on its name or UID.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
            description: A more complete description of the to-do item than provided by the item name.
            due_date: The date the to-do item is expected to be completed.
            due_datetime: The date and time the to-do item is expected to be completed.
            rename: The new name for the to-do item.
            status: A status for the to-do item.
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
        """Removes an existing to-do list item by its name or UID.

        Args:
            item: The name/summary of the to-do item. If you have items with duplicate names, you can reference specific
                ones using their UID instead.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="remove_item",
            target={"entity_id": self.entity.entity_id},
            item=item,
        )

    def remove_completed_items(self) -> None:
        """Removes all to-do list items that have been completed."""
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="remove_completed_items",
            target={"entity_id": self.entity.entity_id},
        )
