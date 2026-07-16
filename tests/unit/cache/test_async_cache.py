"""Unit tests for hassette.cache.wrapper.AsyncCache."""

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

import hassette.cache
from hassette.cache.protocol import CacheProtocol
from hassette.cache.sync import SyncCache
from hassette.cache.wrapper import AsyncCache


@pytest.fixture
async def cache(tmp_path: Path) -> AsyncIterator[AsyncCache]:
    """A freshly-initialized AsyncCache backed by a real SQLite file in tmp_path."""
    db_path = tmp_path / "cache.db"
    instance = AsyncCache(db_path, default_ttl=None)
    await instance.initialize()
    try:
        yield instance
    finally:
        await instance.close()


async def test_async_cache_satisfies_cache_protocol(cache: AsyncCache) -> None:
    """An initialized AsyncCache is a CacheProtocol-conforming instance."""
    assert isinstance(cache, CacheProtocol)


def test_sync_cache_does_not_satisfy_cache_protocol(tmp_path: Path) -> None:
    """SyncCache does not satisfy CacheProtocol -- it's accessed via `.sync`, never polymorphically."""
    sync_cache = SyncCache(tmp_path / "cache.db")
    assert not isinstance(sync_cache, CacheProtocol)


async def test_initialize_creates_db_file(cache: AsyncCache) -> None:
    """initialize() creates the SQLite file on disk."""
    assert cache.db_path.exists()


async def test_initialize_sets_sync_facade(cache: AsyncCache) -> None:
    """initialize() creates a SyncCache pointing at the same database file."""
    assert isinstance(cache.sync, SyncCache)
    assert cache.sync.db_path == cache.db_path


async def test_set_and_get_round_trip(cache: AsyncCache) -> None:
    """A value stored via set() is returned unchanged by get()."""
    await cache.set("greeting", {"text": "hello", "count": 3})
    assert await cache.get("greeting") == {"text": "hello", "count": 3}


async def test_get_returns_default_when_missing(cache: AsyncCache) -> None:
    """get() returns the provided default when the key doesn't exist."""
    assert await cache.get("missing", default="fallback") == "fallback"
    assert await cache.get("missing") is None


async def test_get_returns_stored_none_without_deleting_entry(cache: AsyncCache) -> None:
    """A cached ``None`` value round-trips as ``None``, not the default, and isn't evicted.

    Regression test: deserialize() must distinguish a legitimately-stored ``None`` from
    a failed unpickle -- otherwise get() would mistake the former for corruption and
    delete a perfectly valid entry.
    """
    await cache.set("flag", None)
    assert await cache.get("flag", default="fallback") is None
    # A second get() confirms the first call did not delete the row as if it were corrupt.
    assert await cache.get("flag", default="fallback") is None


async def test_set_with_no_ttl_uses_instance_default(tmp_path: Path) -> None:
    """set(ttl=None) falls back to the instance default_ttl and expires accordingly."""
    db_path = tmp_path / "cache.db"
    instance = AsyncCache(db_path, default_ttl=1)
    await instance.initialize()
    try:
        await instance.set("k", "v")
        assert await instance.get("k") == "v"
        await asyncio.sleep(1.2)
        assert await instance.get("k") is None
    finally:
        await instance.close()


async def test_set_with_no_ttl_and_no_default_persists_indefinitely(cache: AsyncCache) -> None:
    """set(ttl=None) with no instance default_ttl persists the value with no expiry."""
    await cache.set("persistent", "value")
    await asyncio.sleep(0.05)
    assert await cache.get("persistent") == "value"


async def test_set_ttl_expires_value(cache: AsyncCache) -> None:
    """A value stored with a short ttl expires and get() returns None after it elapses."""
    await cache.set("short-lived", "value", ttl=1)
    assert await cache.get("short-lived") == "value"
    await asyncio.sleep(1.2)
    assert await cache.get("short-lived") is None


async def test_set_ttl_zero_deletes_existing_and_does_not_store(cache: AsyncCache) -> None:
    """set(key, value, ttl=0) deletes any existing entry and does not store the new value."""
    await cache.set("key", "original")
    assert await cache.get("key") == "original"

    await cache.set("key", "new-value", ttl=0)
    assert await cache.get("key") is None


async def test_delete_removes_entry(cache: AsyncCache) -> None:
    """delete() removes the entry so a subsequent get() returns None."""
    await cache.set("key", "value")
    await cache.delete("key")
    assert await cache.get("key") is None


async def test_delete_is_a_no_op_for_missing_key(cache: AsyncCache) -> None:
    """delete() on a nonexistent key does not raise."""
    await cache.delete("never-existed")


async def test_get_or_set_calls_creator_on_miss(cache: AsyncCache) -> None:
    """get_or_set() awaits the creator on a cache miss and stores the result."""
    calls = 0

    async def creator() -> str:
        nonlocal calls
        calls += 1
        return "computed"

    result = await cache.get_or_set("key", creator, ttl=60)
    assert result == "computed"
    assert calls == 1
    assert await cache.get("key") == "computed"


async def test_get_or_set_does_not_call_creator_on_hit(cache: AsyncCache) -> None:
    """get_or_set() returns the cached value without invoking creator when present."""
    await cache.set("key", "already-cached")

    async def creator() -> str:
        raise AssertionError("creator should not be called on a cache hit")

    result = await cache.get_or_set("key", creator)
    assert result == "already-cached"


async def test_get_or_set_does_not_call_creator_on_cached_none(cache: AsyncCache) -> None:
    """get_or_set() treats a cached ``None`` as a hit, not a miss.

    Regression test: ``get()`` returns ``None`` for both a missing key and a
    legitimately-stored ``None`` value, so ``get_or_set()`` must not use ``is not None``
    to detect a hit -- doing so would re-invoke creator and overwrite the cache on
    every call.
    """
    await cache.set("flag", None)

    async def creator() -> str:
        raise AssertionError("creator should not be called when None is the cached value")

    result = await cache.get_or_set("flag", creator)
    assert result is None


async def test_clear_removes_all_entries(cache: AsyncCache) -> None:
    """clear() deletes all stored entries."""
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.clear()
    assert await cache.get("a") is None
    assert await cache.get("b") is None


async def test_clear_runs_incremental_vacuum(cache: AsyncCache) -> None:
    """clear() runs PRAGMA incremental_vacuum after deleting all rows."""
    await cache.set("a", "value")

    executed_sql: list[str] = []
    original_execute = cache._write_conn.execute

    async def spying_execute(sql: str, *args: object, **kwargs: object) -> object:
        executed_sql.append(sql)
        return await original_execute(sql, *args, **kwargs)

    cache._write.execute = spying_execute  # pyright: ignore[reportAttributeAccessIssue]
    try:
        await cache.clear()
    finally:
        cache._write.execute = original_execute  # pyright: ignore[reportAttributeAccessIssue]

    assert any("incremental_vacuum" in sql for sql in executed_sql)


async def test_invalidate_deletes_multiple_keys(cache: AsyncCache) -> None:
    """invalidate() deletes every listed key in one operation."""
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)

    await cache.invalidate("a", "b")

    assert await cache.get("a") is None
    assert await cache.get("b") is None
    assert await cache.get("c") == 3


async def test_invalidate_with_no_keys_is_a_no_op(cache: AsyncCache) -> None:
    """invalidate() with no arguments does not raise."""
    await cache.invalidate()


async def test_close_closes_both_connections(cache: AsyncCache) -> None:
    """close() clears both connection references so further use raises RuntimeError."""
    await cache.close()
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = cache._write_conn
    with pytest.raises(RuntimeError, match="not initialized"):
        _ = cache._read_conn


async def test_initialize_recovers_from_corrupt_database(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A corrupt SQLite file is detected via integrity check, deleted, and recreated.

    The corruption surfaces at the very first PRAGMA statement (empirically confirmed
    with stdlib sqlite3 -- garbage bytes fail with "file is not a database" on the
    first statement that touches the file), which is still inside the single
    try/except wrapping steps 1-3 of initialize().
    """
    db_path = tmp_path / "cache.db"
    db_path.write_bytes(b"not a valid sqlite database" * 10)

    instance = AsyncCache(db_path)
    try:
        with caplog.at_level(logging.WARNING, logger="hassette.cache.wrapper"):
            await instance.initialize()

        assert "failed to initialize" in caplog.text
        # Cache is fully usable after recovery.
        await instance.set("k", "v")
        assert await instance.get("k") == "v"
    finally:
        await instance.close()


async def test_initialize_deletes_wal_and_shm_sidecars_on_corruption(tmp_path: Path) -> None:
    """Corruption recovery deletes -wal/-shm sidecar files alongside the main db file."""
    db_path = tmp_path / "cache.db"
    db_path.write_bytes(b"not a valid sqlite database" * 10)
    wal_path = Path(str(db_path) + "-wal")
    shm_path = Path(str(db_path) + "-shm")
    wal_path.write_bytes(b"stale wal data")
    shm_path.write_bytes(b"stale shm data")

    instance = AsyncCache(db_path)
    try:
        await instance.initialize()
        # The original corrupt sidecars are gone; any fresh WAL/SHM state has different content.
        if wal_path.exists():
            assert wal_path.read_bytes() != b"stale wal data"
        if shm_path.exists():
            assert shm_path.read_bytes() != b"stale shm data"
    finally:
        await instance.close()


def test_cache_package_has_no_to_thread_calls() -> None:
    """Cache package data methods use native aiosqlite, no to_thread wrapping."""
    package_dir = Path(hassette.cache.__file__).parent
    for path in package_dir.glob("*.py"):
        content = path.read_text()
        assert "to_thread" not in content, f"{path} references to_thread; cache must use native async I/O"
