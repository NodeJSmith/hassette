"""Runtime-checkable protocol defining the async cache interface.

Satisfied structurally by :class:`~hassette.cache.wrapper.AsyncCache` and
:class:`~hassette.cache.dummy.DummyCache`. :class:`~hassette.cache.sync.SyncCache`
and :class:`~hassette.cache.dummy.DummySyncCache` do NOT satisfy this protocol --
they expose sync methods and are accessed via ``.sync``, never used
polymorphically alongside the async implementations.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class CacheProtocol(Protocol):
    """Protocol for the async cache interface."""

    async def initialize(self) -> None:
        """Prepare the cache for use (open connections, create schema, etc.)."""
        ...

    async def get(self, key: str, default: T | None = None) -> T | None:
        """Return the cached value for *key*, or *default* if missing or expired."""
        ...

    async def set(self, key: str, value: object, ttl: int | None = None) -> None:
        """Store *value* under *key*.

        ``ttl=None`` falls back to the instance's default TTL. ``ttl=0`` deletes
        any existing entry and does not store the new value.
        """
        ...

    async def delete(self, key: str) -> None:
        """Delete the entry at *key*, if any."""
        ...

    async def get_or_set(self, key: str, creator: Callable[[], Awaitable[T]], ttl: int | None = None) -> T:
        """Return the cached value for *key*, computing and storing it via *creator* on miss."""
        ...

    async def clear(self) -> None:
        """Delete all entries and reclaim disk space."""
        ...

    async def invalidate(self, *keys: str) -> None:
        """Delete all listed keys in one operation."""
        ...

    async def close(self) -> None:
        """Release any held resources (connections, etc.)."""
        ...

    @property
    def sync(self) -> Any:
        """Return the synchronous facade for this cache (a ``SyncCache``-like object)."""
        ...
