# App Cache

`self.cache` provides persistent key-value storage on every [`App`](../apps/index.md) instance — no setup required. Data written to the cache survives restarts and is available at the next startup. The cache is a [`diskcache.Cache`](https://grantjenks.com/docs/diskcache/) instance backed by a third-party disk-based storage library. The full diskcache API is available directly.

For real-time Home Assistant entity state, [`self.states`](../states/index.md) (the local state cache) is the right tool. `self.cache` is for app data: counters, timestamps, API responses, preferences.

## Basic Usage

The cache exposes a dictionary-like API for get, set, delete, and membership checks. No open, flush, or close call is needed.

```python
--8<-- "pages/core-concepts/cache/snippets/cache_basic_usage.py"
```

Hassette opens the cache at first access and flushes it to disk at shutdown. All reads and writes happen transparently in between.

## Shared Cache and Multi-Instance Apps

All instances of the same app class share one cache directory, keyed by class name. Two instances of `WeatherApp` with different configurations read from and write to the same cache.

Hassette can run the same app class multiple times with different configs (see [App Instances](../apps/index.md)). For multi-instance apps, prefixing keys with `self.app_config.instance_name` (set per `[[hassette.apps.<key>.config]]` block in `hassette.toml`; defaults to `ClassName.0`, `ClassName.1`, ... when omitted) avoids collisions:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_instance_prefix.py"
```

## What Can Be Cached

The cache stores any Python object that supports pickling, Python's built-in serialization format. This includes:

- Primitives: `str`, `int`, `float`, `bool`, `None`
- Collections: `list`, `dict`, `tuple`, `set`
- Timestamps from the [`whenever`](https://whenever.readthedocs.io/) library (Hassette's date/time library): `Instant`, `ZonedDateTime`, `PlainDateTime`, `TimeDelta`
- Pydantic models and dataclasses (if picklable)

!!! tip "Storing timestamps"
    `self.now()` — a built-in `App` method returning the current time as a timezone-aware [`ZonedDateTime`](https://whenever.readthedocs.io/) — and all `whenever` types are picklable. Store them directly in the cache without conversion.

## Configuration

`default_cache_size` and `data_dir` are root-level settings in `hassette.toml`:

```toml
[hassette]
default_cache_size = 104857600  # 100 MiB (default)
data_dir = "/path/to/data"
```

| Setting | Type | Default | Description |
|---|---|---|---|
| `default_cache_size` | integer (bytes) | `104857600` | Size limit for each app's cache. Least-recently-used items are evicted when the limit is reached. |
| `data_dir` | path | platform-dependent | Root directory for all persistent data. See [Global Settings](../configuration/index.md) for platform defaults. |

## How It Works

**Storage location.** Each app's cache lives at `{data_dir}/{ClassName}/cache/`. A `WeatherApp` with `data_dir = /home/user/.hassette` stores its cache at `/home/user/.hassette/WeatherApp/cache/`.

**Lazy initialization.** The cache directory is created on first access. Apps that never use `self.cache` produce no directory.

**Lifecycle.** The cache is available from first access through shutdown. Hassette closes and flushes it to disk when the app stops.

**Automatic cleanup.** Entries with a TTL expire silently. When the cache reaches its size limit (the `default_cache_size` setting), the least-recently-used items are evicted without raising an error. To set a TTL, use `self.cache.set()` instead of bracket assignment:

```python
self.cache.set("weather_data", payload, expire=3600)  # expires after 1 hour
```

## Verify It Works

Check that cache data persists across restarts with `hassette log`:

```
hassette log --app my_app --since 1h
```

Set `log_level = "DEBUG"` in `hassette.toml` first — cache reads and writes only appear in the log at that level. The cache directory at `{data_dir}/{ClassName}/cache/` contains SQLite files managed by diskcache after the first successful write; the filenames are internal, not meant for inspection.

## See Also

- [Patterns & Examples](patterns.md). Rate-limiting, counters, complex data, expiring entries, and troubleshooting.
- [Global Settings](../configuration/index.md). `data_dir` and `default_cache_size` reference.
- [States](../states/index.md). Real-time HA entity state (not the cache).
- [diskcache documentation](https://grantjenks.com/docs/diskcache/). The underlying library.
