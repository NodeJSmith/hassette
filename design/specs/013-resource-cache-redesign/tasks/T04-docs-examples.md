---
task_id: "T04"
title: "Rewrite cache docs, update snippets and example app"
status: "planned"
depends_on: ["T03"]
implements: ["AC#13", "AC#14"]
---

## Summary

Rewrite the cache documentation pages for the new async/sync API, update all code snippets, delete the obsolete instance-prefix snippet, update the `cover_scheduler` example app, and fix neighboring docs pages that reference the old cache API. This task touches only documentation and example code — no framework source changes.

## Target Files

- modify: `docs/pages/core-concepts/cache/index.md`
- modify: `docs/pages/core-concepts/cache/patterns.md`
- modify: `docs/pages/core-concepts/cache/snippets/cache_basic_usage.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_expire.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_expiring.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_api_response.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_complex_data.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_counter.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_performance.py`
- modify: `docs/pages/core-concepts/cache/snippets/cache_rate_limit.py`
- delete: `docs/pages/core-concepts/cache/snippets/cache_instance_prefix.py`
- modify: `examples/cover_scheduler.py`
- modify: `docs/pages/core-concepts/apps/index.md`
- modify: `docs/pages/core-concepts/apps/snippets/apps_cache_counter.py`
- modify: `docs/pages/migration/concepts.md`
- read: `src/hassette/cache/protocol.py` (CacheProtocol interface — from T01)
- read: `src/hassette/cache/wrapper.py` (AsyncCache API — from T01)
- read: `src/hassette/cache/sync.py` (SyncCache API — from T01)
- read: `src/hassette/cache/dummy.py` (DummyCache — from T01)
- read: `design/specs/013-resource-cache-redesign/design.md` (## Documentation Updates, ## User Scenarios)

## Prompt

### Cache docs — full rewrite

**`index.md`** — Rewrite completely. Document:
- `self.cache` is now an async cache (not raw diskcache). All data methods are `async`.
- Basic usage: `await self.cache.set("key", value)`, `result = await self.cache.get("key")`
- `get_or_set` for lazy population with async creator
- TTL configuration: per-call `ttl=` parameter, class attribute `default_cache_ttl`, global `default_cache_ttl` in HassetteConfig
- `ttl=0` deletes and does not store
- Sync access via `self.cache.sync` for AppSync apps
- Instance-scoped directories (each app instance gets its own cache)
- `cache_key` override in hassette.toml for preserving cache across app renames
- DummyCache for test isolation
- Remove all references to diskcache, `expire=` parameter, dict-style access (`self.cache["key"]`), `size_limit`

**`patterns.md`** — Rewrite all patterns for async API. Replace `self.cache["key"] = value` with `await self.cache.set("key", value)`. Replace `self.cache.get("key", default)` with `result = await self.cache.get("key")` (note: the new API uses `default=None` parameter, not positional). Replace `self.cache.set("key", value, expire=N)` with `await self.cache.set("key", value, ttl=N)`.

### Snippet files — rewrite each

Every snippet is a complete, runnable example App. Convert all to async API:
- Replace dict-style access with async method calls
- Replace `expire=` with `ttl=`
- All cache calls must use `await`
- Keep the App pattern intact (extend `App[Config]`, use `on_initialize`, etc.)

Delete `cache_instance_prefix.py` — instance scoping is now automatic via `cache_key`, no user action needed.

### Example app (`examples/cover_scheduler.py`)

Convert cache usage from dict-style to async API:
- Line 34: `cached = self.cache.get(CACHE_KEY_POSITIONS)` → `cached = await self.cache.get(CACHE_KEY_POSITIONS)`
- Line 83: `self.cache[CACHE_KEY_POSITIONS] = positions` → `await self.cache.set(CACHE_KEY_POSITIONS, positions)`
- Line 110: `self.cache[CACHE_KEY_POSITIONS] = positions` → `await self.cache.set(CACHE_KEY_POSITIONS, positions)`

### Neighboring docs — targeted updates

**`docs/pages/core-concepts/apps/index.md`**:
- Line 3: Update "a set of typed accessors" description — `self.cache` is now an async cache, not a disk-backed store
- Line 148: Update the cache description to reflect async API

**`docs/pages/core-concepts/apps/snippets/apps_cache_counter.py`**:
This snippet is embedded in `apps/index.md` via `--8<-- [start:cache_counter]` section markers. It currently uses dict-style cache access (`self.cache.get("counter", 0)`, `self.cache["counter"] = ...`). Convert to async API:
- `self.cache.get("counter", 0)` → `await self.cache.get("counter")` (with manual default: `or 0`)
- `self.cache["counter"] = self.counter` → `await self.cache.set("counter", self.counter)`

**`docs/pages/migration/concepts.md`**:
- Line 37: Update the `self.cache` row in the concepts table — it's now an async cache backed by aiosqlite, not raw diskcache

## Focus

- The current snippets use `self.cache["key"]`, `self.cache.get("key", default)`, `self.cache.set("key", value, expire=N)` — all of these change to async method calls.
- `cover_scheduler.py` uses `self.cache.get()` and `self.cache[key] = value` (dict-style assignment). The `get()` signature changes (add `await`, `default` is now a keyword argument).
- The `apps/index.md` and `migration/concepts.md` files are gap-check findings — they reference cache as a "disk-backed store" which is technically still true (aiosqlite writes to disk) but the API description needs updating to mention it's async.
- All snippet files should be valid Python that would actually run in a hassette App. Import the right types.
- The design doc's User Scenarios section shows the exact API calls users will write — use these as the source of truth for doc examples.

## Verify

- [ ] AC#13: Cache docs pages rewritten — no references to diskcache, dict-style access, or `expire=` parameter. All examples use `await` with async methods.
- [ ] AC#14: `examples/cover_scheduler.py` uses the new async cache API — no dict-style access, all cache calls use `await`
