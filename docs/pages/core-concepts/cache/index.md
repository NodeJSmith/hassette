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

Each app instance gets its own cache directory and its own SQLite file. Two instances of the same `WeatherApp` class — say, one per city — do not share cache data, so a key like `"last_forecast"` in one instance never collides with another's copy.

The default directory is `{data_dir}/{app_key}/{instance_name}/cache/cache.db`. Reordering `config` blocks leaves each instance's cache with it, and renaming an instance starts a new cache.

!!! warning "Device names on Windows"
    On a native Windows host, an instance named after a reserved device, such as `con`, `nul` or `aux`, has an unusable default cache directory. Another instance name or an explicit `cache_key` avoids the problem.

`cache_key` on an app's section in `hassette.toml` overrides the default directory. The most common reason is preserving cache data across an app rename:

```toml
--8<-- "pages/core-concepts/cache/snippets/cache_key_override.toml"
```

When `cache_key` is set, Hassette uses it as-is with no instance name appended. Two apps that resolve to the same `cache_key` share one cache file. Sharing is usually a mistake, so Hassette logs a startup warning when different `app_key` values resolve to the same `cache_key`.

Intentional sharing is declared with `cache_shared = true` on every app that shares the key:

```toml
--8<-- "pages/core-concepts/cache/snippets/cache_shared.toml"
```

The warning is skipped only when every app sharing the key sets `cache_shared`. When any of them omits it, the warning still fires and names the apps missing the flag. A new app that accidentally lands on a shared key is still caught.

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

When none of these are set, entries persist indefinitely. Both `default_cache_ttl` settings are in seconds, like `ttl`. A class-level default applies to every `set` call in the app that omits `ttl`:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_default_ttl.py"
```

The global fallback covers every app that sets no class-level default:

```toml
--8<-- "pages/core-concepts/cache/snippets/cache_global_ttl.toml"
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

`DummyCache` is an in-memory implementation of the same interface. Pass it to `App.__init__` via the `cache` parameter — or use the `dummy_cache` pytest fixture from `hassette.testing` — to exercise cache-using code without touching disk. `DummyCache` supports the full API — `get`, `set`, `delete`, `get_or_set`, `clear`, `invalidate`, and `.sync` — with the same TTL semantics as the real cache.

The `dummy_cache` fixture isn't auto-discovered. Register it once in `conftest.py`:

```python
pytest_plugins = ["hassette.testing.fixtures"]
```

This makes `dummy_cache` available to every test in the suite.

## What Can Be Cached

The cache stores any Python object that supports pickling, Python's built-in serialization format:

- Primitives: `str`, `int`, `float`, `bool`, `None`
- Collections: `list`, `dict`, `tuple`, `set`
- Timestamps from the [`whenever`](https://whenever.readthedocs.io/) library: `Instant`, `ZonedDateTime`, `PlainDateTime`, `TimeDelta`
- Pydantic models and dataclasses (if picklable)

!!! tip "Storing timestamps"
    `self.now()` — a built-in `App` method returning the current time as a timezone-aware [`ZonedDateTime`](https://whenever.readthedocs.io/) — and all `whenever` types are picklable. Store them directly without conversion.

## Verify It Works

A run counter shows whether cache data survives a restart. This app reads `run_count`, stores it incremented, and logs the new value:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_run_count.py"
```

Restart Hassette, then read the app's log:

```
hassette log --app my_app --since 1h
```

Each restart logs a count one higher than the last. A count stuck at `1` means the cache file isn't persisting.

!!! note
    Corruption and deserialization failures are logged as warnings. Normal cache reads and writes produce no log output.

## See Also

- [Patterns & Examples](patterns.md). Rate-limiting, counters, complex data, expiring entries, and troubleshooting.
- [Global Settings](../configuration/index.md). `data_dir` reference.
- [States](../states/index.md). Real-time HA entity state (not the cache).
