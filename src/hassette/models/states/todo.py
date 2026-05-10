from enum import IntFlag, StrEnum
from typing import Any, Literal

from pydantic import Field

from .base import AttributesBase, NumericBaseState


class TodoServices(StrEnum):
    ADD_ITEM = "add_item"
    UPDATE_ITEM = "update_item"
    REMOVE_ITEM = "remove_item"
    GET_ITEMS = "get_items"
    REMOVE_COMPLETED_ITEMS = "remove_completed_items"


class TodoItemStatus(StrEnum):
    NEEDS_ACTION = "needs_action"
    COMPLETED = "completed"


class TodoListEntityFeature(IntFlag):
    CREATE_TODO_ITEM = 1
    DELETE_TODO_ITEM = 2
    UPDATE_TODO_ITEM = 4
    MOVE_TODO_ITEM = 8
    SET_DUE_DATE_ON_ITEM = 16
    SET_DUE_DATETIME_ON_ITEM = 32
    SET_DESCRIPTION_ON_ITEM = 64


class TodoAttributes(AttributesBase):
    todo_items: list[Any] | None = Field(default=None)

    @property
    def supports_create_todo_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.CREATE_TODO_ITEM)

    @property
    def supports_delete_todo_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.DELETE_TODO_ITEM)

    @property
    def supports_update_todo_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.UPDATE_TODO_ITEM)

    @property
    def supports_move_todo_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.MOVE_TODO_ITEM)

    @property
    def supports_set_due_date_on_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.SET_DUE_DATE_ON_ITEM)

    @property
    def supports_set_due_datetime_on_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.SET_DUE_DATETIME_ON_ITEM)

    @property
    def supports_set_description_on_item(self) -> bool:
        return self._has_feature(TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM)


class TodoState(NumericBaseState):
    """Representation of a Home Assistant todo state.

    See: https://www.home-assistant.io/integrations/todo/
    """

    domain: Literal["todo"]

    attributes: TodoAttributes
