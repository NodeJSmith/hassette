# App Cache

`self.cache` stores values that survive app restarts — counters, timestamps, API responses, user preferences. Every `App` instance gets one automatically, backed by its own SQLite database file. No setup required.

For real-time Home Assistant entity state, [`self.states`](../states/index.md) is the right tool. `self.cache` is for app data, not entity state.

## Basic Usage

Every data method on `self.cache` is `async` and must be awaited:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_basic_usage.py"
```

`get` returns `None` when a key is missing, or the value passed as `default` when one is given. `set` stores a value indefinitely unless a `ttl` is given (see [TTL and Expiration](#ttl-and-expiration) below). `delete` removes a key; deleting a missing key is a no-op.

## Instance-Scoped Directories

Each app instance gets its own cache directory and its own SQLite file. Two instances of the same `WeatherApp` class — say, one per city — do not share cache data, so a key like `"last_forecast"` in instance 0 never collides with instance 1's copy.

The default directory is `{data_dir}/{app_key}/{index}/cache/cache.db`. Set `cache_key` on an app's section in `hassette.toml` to override this — the most common reason is preserving cache data across an app rename:

```toml
[hassette.apps.weather]
cache_key = "weather_v1/0"  # keep the cache from before the app was renamed
```

When `cache_key` is set, Hassette uses it as-is with no index appended. Two apps that intentionally share a `cache_key` share one cache file; Hassette logs a warning at startup if two *different* `app_key` values resolve to the same `cache_key` unintentionally.

## Lazy Population with `get_or_set`

`get_or_set` reads a key, and on a miss, calls an async function to compute the value, stores it, and returns it:

```python
data = await self.cache.get_or_set("weather", fetch_weather, ttl=3600)
```

`fetch_weather` only runs when the cache misses or the entry expired. Subsequent calls within the TTL window return the stored value without calling `fetch_weather` again.

## TTL and Expiration

`set` accepts a `ttl` parameter in seconds:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_expire.py:expire"
```

The entry expires after the given number of seconds; `get` returns `None` for an expired key and removes it from storage. Three levels resolve the default when `ttl` is omitted, in order:

1. The per-call `ttl` argument to `set`
2. The app subclass's `default_cache_ttl` class attribute
3. `default_cache_ttl` in `hassette.toml` (a global fallback under `[hassette]`)

When none of these are set, entries persist indefinitely. An app that sets a class-level default looks like this:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_expiring.py"
```

!!! warning "`ttl=0` deletes, it doesn't store"
    `set(key, value, ttl=0)` deletes any existing entry at `key` and does not store the new value. Use `delete(key)` if that's the intent — `ttl=0` exists to let a computed TTL of zero (e.g., "already expired") behave the same way.

## Synchronous Access

[`AppSync`](../apps/index.md#synchronous-apps) apps run their lifecycle hooks and handlers in a thread pool, without `async`/`await`. `self.cache.sync` exposes the same methods as plain synchronous calls:

```python
self.cache.sync.set("temp", reading, ttl=300)
val = self.cache.sync.get("temp")
```

`self.cache.sync` opens its own connection to the same SQLite file — it works from `AppSync` handlers, but calling it from inside a running event loop raises `RuntimeError`, matching the safety contract of `self.bus.sync`, `self.scheduler.sync`, and `self.api.sync`.

## Test Isolation with DummyCache

`DummyCache` is an in-memory implementation of the same interface. Pass it to `App.__init__` via the `cache` parameter — or use the `dummy_cache` pytest fixture from `hassette.test_utils` — to exercise cache-using code without touching disk. `DummyCache` supports the full API — `get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`, and `.sync` — with the same TTL semantics as the real cache.

## What Can Be Cached

The cache stores any Python object that supports pickling, Python's built-in serialization format:

- Primitives: `str`, `int`, `float`, `bool`, `None`
- Collections: `list`, `dict`, `tuple`, `set`
- Timestamps from the [`whenever`](https://whenever.readthedocs.io/) library: `Instant`, `ZonedDateTime`, `PlainDateTime`, `TimeDelta`
- Pydantic models and dataclasses (if picklable)

!!! tip "Storing timestamps"
    `self.now()` — a built-in `App` method returning the current time as a timezone-aware [`ZonedDateTime`](https://whenever.readthedocs.io/) — and all `whenever` types are picklable. Store them directly without conversion.

## Verify It Works

Check that cache data persists across restarts with `hassette log`:

```
hassette log --app my_app --since 1h
```

Set `log_level = "DEBUG"` in `hassette.toml` first — cache reads and writes only appear in the log at that level.

## See Also

- [Patterns & Examples](patterns.md). Rate-limiting, counters, complex data, expiring entries, and troubleshooting.
- [Global Settings](../configuration/index.md). `data_dir` reference.
- [States](../states/index.md). Real-time HA entity state (not the cache).
