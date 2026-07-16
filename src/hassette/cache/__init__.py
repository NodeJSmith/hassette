"""Async, sync, and dummy cache implementations backed by aiosqlite/sqlite3.

Cache is App-only -- framework Resources do not have a ``.cache`` accessor. All
classes here are plain objects with explicit lifecycle management; none are
``Resource`` subclasses.
"""

from hassette.cache.dummy import DummyCache, DummySyncCache
from hassette.cache.protocol import CacheProtocol
from hassette.cache.sync import SyncCache
from hassette.cache.wrapper import AsyncCache

__all__ = ["AsyncCache", "CacheProtocol", "DummyCache", "DummySyncCache", "SyncCache"]
