import typing
from collections.abc import Coroutine
from typing import Any, Generic, cast

from pydantic import BaseModel, ConfigDict, PrivateAttr

from hassette import context
from hassette.types import StateT, StateValueT

if typing.TYPE_CHECKING:
    from hassette import Api, Hassette


EntityT = typing.TypeVar("EntityT", bound="BaseEntity", covariant=True)
"""Represents a specific entity type, e.g., LightEntity, SensorEntity, etc."""

# Internal (underscore -> excluded from the generated entities __all__): the facade type a
# domain entity's .sync property creates and caches via _get_or_create_sync.
_FacadeT = typing.TypeVar("_FacadeT", bound="BaseEntitySyncFacade[Any, Any]")


class BaseEntity(BaseModel, Generic[StateT, StateValueT]):
    """Base class for all entities."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    state: StateT
    _sync: "BaseEntitySyncFacade[StateT, StateValueT] | None" = PrivateAttr(default=None, init=False)

    async def refresh(self) -> StateT:
        self.state = cast("StateT", await self.hassette.api.get_state(self.entity_id))
        return self.state

    @property
    def value(self) -> StateValueT:
        return cast("StateValueT", self.state.value)

    @property
    def entity_id(self) -> str:
        return self.state.entity_id

    @property
    def domain(self) -> str:
        return self.state.domain

    @property
    def hassette(self) -> "Hassette":
        """Get the Hassette instance for this entity.

        Resolved at call time from the active Hassette context, not stored on the entity.
        An entity used after the context that created it is torn down (a different thread,
        a reset ContextVar, app shutdown) raises ``RuntimeError``.
        """

        inst = context.HASSETTE_INSTANCE.get(None)
        if inst is None:
            raise RuntimeError("Hassette instance not set in context")

        return inst

    @property
    def api(self) -> "Api":
        """Get the Hassette API instance for this entity. Resolved at call time (see the ``hassette`` property)."""
        return self.hassette.api

    def _get_or_create_sync(self, facade_cls: type[_FacadeT]) -> _FacadeT:
        """Return the cached sync facade, creating it from ``facade_cls`` on first access.

        Single caching authority for ``.sync`` — domain entities override only the facade
        type via their ``sync`` property, not this caching logic. Unsafe to call with a
        ``facade_cls`` that disagrees with an already-cached instance, so it raises rather
        than hand back a wrongly-typed facade (e.g. a subclass that forgot to override ``sync``).
        """
        if self._sync is None:
            self._sync = facade_cls(entity=self)
        if not isinstance(self._sync, facade_cls):
            raise TypeError(f"Cached sync facade is {type(self._sync).__name__}, expected {facade_cls.__name__}")
        return self._sync

    @property
    def sync(self) -> "BaseEntitySyncFacade[StateT, StateValueT]":
        """Return the typed synchronous facade for this entity."""
        return self._get_or_create_sync(BaseEntitySyncFacade)

    def turn_off(self) -> Coroutine[Any, Any, None]:
        """Turn off the entity.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.turn_off(self.entity_id, self.domain)

    def turn_on(self, **data: Any) -> Coroutine[Any, Any, None]:
        """Turn on the entity.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.turn_on(self.entity_id, self.domain, **data)

    def toggle(self) -> Coroutine[Any, Any, None]:
        """Toggle the entity.

        Must be awaited — a forgotten ``await`` is reported per ``forgotten_await_behavior`` (default: warn).
        """
        # Shape B delegate — returns the callee's handle directly (no await, no second guard_await).
        # The single guard_await lives at api.call_service (the true primary). See design/071.
        return self.api.toggle_service(self.entity_id, self.domain)


class BaseEntitySyncFacade(Generic[StateT, StateValueT]):
    """Synchronous facade for BaseEntity to allow easier access to properties without async/await."""

    entity: BaseEntity[StateT, StateValueT]

    def __init__(self, entity: BaseEntity[StateT, StateValueT]) -> None:
        self.entity = entity

    def turn_off(self) -> None:
        """Turn off the entity.

        Returns:
            None.
        """
        self.entity.api.sync.turn_off(self.entity.entity_id, self.entity.domain)

    def turn_on(self, **data: Any) -> None:
        """Turn on the entity.

        Args:
            **data: Service data fields forwarded to the domain's ``turn_on`` service.

        Returns:
            None.
        """
        self.entity.api.sync.turn_on(self.entity.entity_id, self.entity.domain, **data)

    def toggle(self) -> None:
        """Toggle the entity.

        Returns:
            None.
        """
        self.entity.api.sync.toggle_service(self.entity.entity_id, self.entity.domain)
