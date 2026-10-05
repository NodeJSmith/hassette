"""Pyright probe proving cache ``get()`` narrows its return type when a non-None default is passed."""

# ruff: noqa
# pyright: basic

from typing import Any, assert_type

from hassette.cache.dummy import DummyCache, DummySyncCache
from hassette.cache.protocol import CacheProtocol
from hassette.cache.sync import SyncCache
from hassette.cache.wrapper import AsyncCache


async def probe_async_get(cache: CacheProtocol, async_cache: AsyncCache, dummy: DummyCache) -> None:
    for c in (cache, async_cache, dummy):
        with_default: list[float] = await c.get("key", default=[])
        assert_type(await c.get("key", default=0), int)
        assert_type(await c.get("key"), Any | None)
        assert_type(await c.get("key", default=None), Any | None)


def probe_sync_get(sync_cache: SyncCache, dummy_sync: DummySyncCache) -> None:
    for c in (sync_cache, dummy_sync):
        with_default: list[float] = c.get("key", default=[])
        assert_type(c.get("key", default=0), int)
        assert_type(c.get("key"), Any | None)
        assert_type(c.get("key", default=None), Any | None)
