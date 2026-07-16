---
task_id: "T03"
title: "Wire cache into App, remove from Resource, update test infra"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#2", "FR#7", "FR#8", "FR#10", "FR#13", "FR#14", "AC#1", "AC#2", "AC#10", "AC#11", "AC#12", "AC#16", "AC#17", "AC#18", "AC#19", "AC#20"]
---

## Summary

Wire the cache package into App's lifecycle, remove cache from the Resource base class, remove the diskcache dependency, update the test infrastructure, remove obsolete tests, and extend the pyright forgotten-await probe. This is the integration task — it connects T01's cache package and T02's config changes into the framework.

## Target Files

- modify: `src/hassette/app/app.py`
- modify: `src/hassette/resources/base.py`
- modify: `pyproject.toml`
- modify: `src/hassette/test_utils/mock_hassette.py`
- modify: `src/hassette/test_utils/fixtures.py`
- modify: `tests/unit/resources/test_resource_properties.py`
- modify: `tests/unit/resources/test_shutdown_edge_cases.py`
- modify: `tests/pyright_probes/forgotten_await_probe.py`
- read: `src/hassette/config/classes.py` (AppManifest.cache_key — from T02)
- read: `src/hassette/cache/` (cache package — from T01)
- read: `src/hassette/core/database_service.py` (shutdown ordering convention)
- read: `design/specs/013-resource-cache-redesign/design.md` (## Architecture → Changes to App, Changes to Resource)

## Prompt

### App changes (`src/hassette/app/app.py`)

**Constructor** — Add `cache: CacheProtocol | None = None` parameter to `App.__init__`. When provided (test injection), store it directly as `self.cache`. When None (production), construct `AsyncCache(db_path, default_ttl)` where:
- `db_path = hassette.config.data_dir / self.cache_key / "cache" / "cache.db"`
- `default_ttl` resolved from: `cls.default_cache_ttl` if set on the class → `hassette.config.default_cache_ttl` → None

Verify `"cache"` is in `_APP_PUBLIC_API` (frozenset starting at line 27, `"cache"` entry at line 46) — it's already there; just confirm it stays.

**Class attribute** — Add `default_cache_ttl: ClassVar[int | None] = None` to the App class body.

**Property** — Add `cache_key` property:
```python
@property
def cache_key(self) -> str:
    if self.app_manifest and self.app_manifest.cache_key:
        return self.app_manifest.cache_key
    return f"{self.app_key}/{self.index}"
```

**Lifecycle** — `App` does not currently override `before_initialize`. Add it:
```python
async def before_initialize(self) -> None:
    if isinstance(self.cache, AsyncCache):
        await self.cache.initialize()
```

When cache was injected (DummyCache), skip initialization — DummyCache.initialize() is a no-op but the guard avoids the call for clarity.

**Cleanup** — Update `App.cleanup()` (currently at line 197, `@final`). After `await super().cleanup()`, add `await self.cache.close()` wrapped in try/except to swallow errors (matching the existing error-swallowing pattern from `base.py:567-571`).

**AppSync** — `AppSync.before_initialize` (line 231) currently does NOT call `super()`. Update it to call `await super().before_initialize()` FIRST, then run the sync wrapper:
```python
@final
async def before_initialize(self) -> None:
    await super().before_initialize()
    await self.task_bucket.run_in_thread(self.before_initialize_sync)
```

### Resource cleanup (`src/hassette/resources/base.py`)

Remove these items:
1. Line 9: `from diskcache import Cache`
2. Lines 106-107: `_cache: Cache | None` class annotation and docstring
3. Line 165: `self._cache = None` in `__init__`
4. Lines 220-230: `cache` cached_property and its implementation
5. Lines 567-571: cache-close logic in `cleanup()`

After removing the diskcache import, also remove `functools.cached_property` from imports (line 5) if nothing else uses it in the file. Check first — `unique_name` is a `@property`, not `@cached_property`, so `cached_property` may only be used by `cache`.

### Dependency removal (`pyproject.toml`)

Remove `"diskcache>=5.6.3"` from the `dependencies` list (line 48).

### Test infrastructure

**`mock_hassette.py`** — If not already handled in T02, remove any remaining `default_cache_size` references.

**`fixtures.py`** or appropriate test_utils file — Add a DummyCache fixture or factory function that tests can use to inject DummyCache into App instances.

**`test_resource_properties.py`** — Remove the entire `TestCache` class (3 tests: `test_cache_builds_directory_and_returns_cache_instance`, `test_cache_is_memoized_across_accesses`, `test_cache_returns_preset_cache_without_reconstruction`). Remove the `from diskcache import Cache` import.

**`test_shutdown_edge_cases.py`** — Remove the `TestCleanupCache` class (2 tests: `test_cleanup_closes_present_cache`, `test_cleanup_swallows_cache_close_exception`). Remove the `_FakeCacheOk` and `_FakeCacheRaises` helper classes.

### Pyright probe extension (`tests/pyright_probes/forgotten_await_probe.py`)

Add AsyncCache probe cases. Create an `_make_cache()` helper that constructs an AsyncCache mock (similar to existing `_make_bus`, `_make_api` helpers). Add bare un-awaited calls to `cache.get()`, `cache.set()`, `cache.get_or_set()` in `probe_cases()` to verify pyright catches them.

### New tests for this task

Add tests verifying:
- Two App instances with different indices get different `cache_key` values (and therefore different directories)
- App with injected DummyCache uses it (no AsyncCache construction)
- App.cleanup() closes the cache
- App.cleanup() swallows cache close exceptions
- AppSync.before_initialize calls super() (cache init fires for sync apps)
- TTL resolution chain: App subclass with `default_cache_ttl = 60` produces AsyncCache with `default_ttl=60`
- TTL resolution fallback: App subclass without `default_cache_ttl` + `HassetteConfig.default_cache_ttl = 120` produces AsyncCache with `default_ttl=120`
- TTL resolution none: neither set → AsyncCache with `default_ttl=None`

## Focus

- `App.__init__` at `app.py:137` — the constructor takes `hassette`, `app_config`, `index`, `app_key`, `app_manifest`, `api_factory`, `parent`. Add `cache` after `parent`.
- `App.cleanup()` at `app.py:197` — currently just calls `super().cleanup()`. Add cache close after it.
- `AppSync.before_initialize` at `app.py:231` — currently `@final`, does NOT call `super()`. This is the critical fix: without `super()`, cache init never fires for sync apps.
- `Resource.__init__` sets `self._cache = None` at line 165 — this must be removed, not just the property.
- `cached_property` import at `base.py:5` — verify no other use before removing. `unique_name` (line 232) is a `@property`, not `@cached_property`.
- The pyright probe file uses `# pyright: ignore[reportAttributeAccessIssue]` liberally on mock setup lines. The probe's own pyrightconfig.json sets `reportAttributeAccessIssue: "none"`, so new cache mock setup won't need these suppressions.
- AC#12 — run `prek -a && prek pyright -a --stage pre-push` after all changes. Plain `prek -a` only runs ruff; pyright is staged as pre-push and requires the explicit second command.

## Verify

- [ ] FR#1: `isinstance(app.cache, CacheProtocol)` returns True for a production App instance
- [ ] FR#2: Two App instances with same app_key but different index produce different cache directories
- [ ] FR#10: App constructed with `cache=DummyCache()` uses the DummyCache — no AsyncCache created
- [ ] FR#13: App with manifest `cache_key="custom"` produces `cache_key` property returning "custom". App without manifest cache_key produces `f"{app_key}/{index}"`
- [ ] FR#7: An App subclass with `default_cache_ttl = 60` uses that value as the resolved `default_ttl` passed to AsyncCache
- [ ] FR#8: When App subclass has no `default_cache_ttl`, `HassetteConfig.default_cache_ttl` is used as the fallback
- [ ] FR#14: `App.cleanup()` calls `AsyncCache.close()` which closes connections
- [ ] AC#1: `isinstance(app.cache, CacheProtocol)` — verified
- [ ] AC#2: Two test App instances with different indices produce different cache directory paths
- [ ] AC#10: DummyCache injected via constructor makes `app.cache` return it
- [ ] AC#11: Existing tests in `test_resource_properties.py` and `test_shutdown_edge_cases.py` pass (cache tests removed, other tests unchanged)
- [ ] AC#12: `prek -a && prek pyright -a --stage pre-push` passes with no new errors
- [ ] AC#16: `diskcache` removed from `pyproject.toml` dependencies
- [ ] AC#19: No `to_thread` calls in the `src/hassette/cache/` package (grep verification)
- [ ] AC#17: An App subclass with `default_cache_ttl = 60` produces an AsyncCache whose `default_ttl` is 60 — a `set()` without explicit `ttl` uses it
- [ ] AC#18: When App subclass has no `default_cache_ttl`, `HassetteConfig.default_cache_ttl = 120` is used as the fallback `default_ttl` on the AsyncCache
- [ ] AC#20: `hasattr(resource, 'cache')` is False for non-App Resources
