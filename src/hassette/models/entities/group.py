from collections.abc import Coroutine
from typing import Any

from hassette.models.states import GroupState
from hassette.models.states.group import GroupAttributes

from .base import BaseEntity, BaseEntitySyncFacade


class GroupEntity(BaseEntity[GroupState, str]):
    @property
    def attributes(self) -> GroupAttributes:
        return self.state.attributes

    @property
    def sync(self) -> "GroupEntitySyncFacade":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(GroupEntitySyncFacade)

    def set(
        self,
        *,
        object_id: str,
        add_entities: list[str] | None = None,
        all: bool | None = None,
        entities: list[str] | None = None,
        icon: str | None = None,
        name: str | None = None,
        remove_entities: list[str] | None = None,
    ) -> Coroutine[Any, Any, None]:
        """Creates or updates a group.

        Args:
            object_id: Object ID of this group. This object ID is used as part of the entity ID. Entity ID format:
                [domain].[object_id].
            add_entities: List of members to be added to the group. Cannot be used in combination with `Entities` or
                `Remove entities`.
            all: Enable this option if the group should only be used when all entities are in state `on`.
            entities: List of all members in the group. Cannot be used in combination with `Add entities` or `Remove
                entities`.
            icon: Name of the icon for the group.
            name: Name of the group.
            remove_entities: List of members to be removed from a group. Cannot be used in combination with `Entities`
                or `Add entities`.
        """
        return self.api.call_service(
            domain=self.domain,
            service="set",
            target={"entity_id": self.entity_id},
            object_id=object_id,
            add_entities=add_entities,
            all=all,
            entities=entities,
            icon=icon,
            name=name,
            remove_entities=remove_entities,
        )

    def remove(
        self,
        *,
        object_id: Any,
    ) -> Coroutine[Any, Any, None]:
        """Removes a group.

        Args:
            object_id: Object ID of this group. This object ID is used as part of the entity ID. Entity ID format:
                [domain].[object_id].
        """
        return self.api.call_service(
            domain=self.domain,
            service="remove",
            target={"entity_id": self.entity_id},
            object_id=object_id,
        )


class GroupEntitySyncFacade(BaseEntitySyncFacade[GroupState, str]):
    """Synchronous facade for GroupEntity service methods."""

    def set(
        self,
        *,
        object_id: str,
        add_entities: list[str] | None = None,
        all: bool | None = None,
        entities: list[str] | None = None,
        icon: str | None = None,
        name: str | None = None,
        remove_entities: list[str] | None = None,
    ) -> None:
        """Creates or updates a group.

        Args:
            object_id: Object ID of this group. This object ID is used as part of the entity ID. Entity ID format:
                [domain].[object_id].
            add_entities: List of members to be added to the group. Cannot be used in combination with `Entities` or
                `Remove entities`.
            all: Enable this option if the group should only be used when all entities are in state `on`.
            entities: List of all members in the group. Cannot be used in combination with `Add entities` or `Remove
                entities`.
            icon: Name of the icon for the group.
            name: Name of the group.
            remove_entities: List of members to be removed from a group. Cannot be used in combination with `Entities`
                or `Add entities`.
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="set",
            target={"entity_id": self.entity.entity_id},
            object_id=object_id,
            add_entities=add_entities,
            all=all,
            entities=entities,
            icon=icon,
            name=name,
            remove_entities=remove_entities,
        )

    def remove(
        self,
        *,
        object_id: Any,
    ) -> None:
        """Removes a group.

        Args:
            object_id: Object ID of this group. This object ID is used as part of the entity ID. Entity ID format:
                [domain].[object_id].
        """
        self.entity.api.sync.call_service(
            domain=self.entity.domain,
            service="remove",
            target={"entity_id": self.entity.entity_id},
            object_id=object_id,
        )
