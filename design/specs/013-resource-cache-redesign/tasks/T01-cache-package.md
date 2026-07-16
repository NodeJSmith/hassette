---
task_id: "T01"
title: "Create cache package with async, sync, and dummy implementations"
status: "done"
depends_on: []
implements: ["FR#1", "FR#3", "FR#4", "FR#5", "FR#6", "FR#9", "FR#11", "FR#12", "AC#3", "AC#4", "AC#5", "AC#6", "AC#7"]
---

## Summary

Create the `src/hassette/cache/` package containing the protocol, shared helpers, AsyncCache (aiosqlite), SyncCache (stdlib sqlite3), and DummyCache (in-memory). This is the foundational task — all new cache code lives here. The package is self-contained with no imports from hassette internals beyond types (it does not import Resource, App, or Config). Unit tests cover each module.

## Target Files

- create: `src/hassette/cache/__init__.py`
- create: `src/hassette/cache/protocol.py`
- create: `src/hassette/cache/_helpers.py`
- create: `src/hassette/cache/wrapper.py`
- create: `src/hassette/cache/sync.py`
- create: `src/hassette/cache/dummy.py`
- create: `tests/unit/cache/__init__.py`
- create: `tests/unit/cache/test_helpers.py`
- create: `tests/unit/cache/test_async_cache.py`
- create: `tests/unit/cache/test_sync_cache.py`
- create: `tests/unit/cache/test_dummy.py`
- read: `src/hassette/core/database_service.py` (WAL mode, busy_timeout, connection pair pattern)
- read: `src/hassette/task_bucket/task_bucket.py` (sync facade loop-safety guard pattern)
- read: `design/specs/013-resource-cache-redesign/design.md` (## Architecture, ## Convention Examples)

## Prompt

Create the `src/hassette/cache/` package. Read the design doc's `## Architecture` section for the full specification of each module.

**`protocol.py`** — Runtime-checkable `CacheProtocol` using `@runtime_checkable Protocol`. Defines the async cache interface: `initialize`, `get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`, `close`, and a `sync` property. `SyncCache` and `DummySyncCache` do NOT satisfy this protocol — they are accessed via `.sync`, never used polymorphically.

**`_helpers.py`** — Module-level free functions shared by AsyncCache and SyncCache (no inheritance):
- `SCHEMA_DDL` — `PRAGMA auto_vacuum = INCREMENTAL` + `CREATE TABLE IF NOT EXISTS cache_entries (key TEXT PRIMARY KEY, value BLOB NOT NULL, expires_at REAL)`
- `resolve_ttl(ttl, default_ttl)` — per-call ttl → instance default_ttl → None (persist indefinitely)
- `serialize(value)` / `deserialize(blob, key)` — pickle serialization. `deserialize` catches `pickle.UnpicklingError`, `AttributeError`, `ModuleNotFoundError`, `EOFError`, logs warning with key name, returns None
- `validate_key(key)` — key validation (non-empty string)

**`wrapper.py`** — `AsyncCache`. Constructor: `AsyncCache(db_path: Path, default_ttl: int | None = None)`. Uses two aiosqlite connections (read/write pair) in WAL mode with `PRAGMA busy_timeout = 5000` (matching `database_service.py:50` `_BUSY_TIMEOUT_MS`). Follow the connection pair pattern from `database_service.py:224-229`.

`initialize()`: Steps 1-3 (connect, CREATE TABLE, PRAGMA integrity_check) wrapped in try/except for `sqlite3.Error`. On failure: close connections, delete SQLite file + `-wal`/`-shm` sidecars, retry once from step 1 with warning log. If retry fails, exception propagates. Step 4: create `self.sync = SyncCache(self.db_path, self.default_ttl)`.

Data methods (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`) are native `async def` using aiosqlite — no `to_thread`. `clear()` runs `PRAGMA incremental_vacuum` after DELETE. `set` with `ttl=0` deletes existing entry and does not store. `get_or_set` takes an async callable `creator`.

`close()` closes both aiosqlite connections. SyncCache has no connection to close.

**`sync.py`** — `SyncCache`. Hand-written using stdlib `sqlite3`. Opens a fresh connection per method call (connect → execute → close). Each connection sets WAL mode and `PRAGMA busy_timeout = 5000`. Every public method starts with `asyncio.get_running_loop()` guard that raises `RuntimeError` — follow the pattern from `task_bucket.py:306-315`. `get_or_set` takes a sync callable. Not a Resource — plain object owned by AsyncCache.

**`dummy.py`** — `DummyCache` + `DummySyncCache`. In-memory dict storing `(value, expires_at)` tuples. `get` returns None for expired entries. `initialize()` and `close()` are no-ops. `.sync` returns `DummySyncCache` with the same dict-backed behavior. `DummySyncCache` enforces the same `asyncio.get_running_loop()` guard as production SyncCache. Constructor: `DummyCache(default_ttl: int | None = None)`.

**`__init__.py`** — Export `AsyncCache`, `SyncCache`, `DummyCache`, `DummySyncCache`, `CacheProtocol`.

**Unit tests:** One test file per module. Use `tmp_path` fixture for AsyncCache/SyncCache tests (real SQLite files). Test the corruption recovery path by writing garbage bytes to the db file before calling `initialize()`. Test `ttl=0` deletion. Test deserialization failure (pickle a class, rename it, verify warning + None return). Test SyncCache's loop-safety guard raises RuntimeError from async context.

## Focus

- The WAL mode + busy_timeout pattern is established in `database_service.py:50,530,537`. Use `_BUSY_TIMEOUT_MS = 5000` as a module constant in `_helpers.py` rather than importing from database_service (cache package should be self-contained).
- `aiosqlite` connection management: use `aiosqlite.connect()` directly (not `_connect_daemon` — that's database_service-specific). Set `isolation_level=None` for autocommit.
- The loop-safety guard pattern in `task_bucket.py:306-315` uses try/except RuntimeError around `asyncio.get_running_loop()`. Adapt the error message for cache context.
- Pickle serialization: use `pickle.dumps`/`pickle.loads` with default protocol. The `deserialize` error handling is important — cached classes can be renamed/moved between restarts.
- `PRAGMA auto_vacuum = INCREMENTAL` must be set BEFORE any table creation (it's a no-op on existing databases) — include it in `SCHEMA_DDL` as the first statement.
- No hassette-internal imports beyond what's in `types/` for type definitions. The cache package must be self-contained.

## Verify

- [ ] FR#1: `AsyncCache` and `DummyCache` both satisfy `CacheProtocol` — `isinstance(cache, CacheProtocol)` returns True
- [ ] FR#3: All async methods exist and work: `get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`. `clear()` runs `PRAGMA incremental_vacuum`
- [ ] FR#4: `cache.sync` returns a `SyncCache` with matching sync method signatures. Calling `.sync.get()` from inside a running event loop raises `RuntimeError`
- [ ] FR#5: `set(key, value)` with no ttl uses instance `default_ttl`. When `default_ttl` is also None, value persists indefinitely
- [ ] FR#6: `set(key, value, ttl=0)` deletes any existing entry and does not store the new value
- [ ] FR#9: `DummyCache` stores in-memory with TTL semantics — `get` returns None for expired entries. `.sync` accessor works with same behavior
- [ ] FR#11: AsyncCache data methods use native aiosqlite — no `to_thread` calls in the cache package
- [ ] FR#12: Corrupt SQLite file is detected during `initialize()`, deleted with sidecars, and recreated with a warning log
- [ ] AC#3: All async interface methods (`get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`) exist and are callable
- [ ] AC#4: `cache.sync` accessor returns a `SyncCache` with matching method signatures. Calling `.sync.get()` from inside a running event loop raises `RuntimeError`
- [ ] AC#5: `set(key, value, ttl=None)` falls back to the instance's pre-resolved `default_ttl`; `set(key, value, ttl=0)` deletes any existing entry and does not store
- [ ] AC#6: `DummyCache` — `set` stores in-memory with TTL, `get` returns `None` for expired entries, `.sync` accessor works
- [ ] AC#7: An `AsyncCache` with a corrupt database file initializes successfully — integrity check detects corruption, file is recreated, warning logged
