# App Cache

Hassette provides a built-in disk-based cache on every app and service via `self.cache`. Data written to the cache persists across restarts and is available immediately the next time your app starts.

## When to Use the Cache

The cache is the right tool when you need to:

- **Rate-limit notifications** — record when you last sent a notification so it does not repeat within a cooldown window
- **Remember state across restarts** — counters, timestamps, or preferences that should survive a Hassette restart
- **Cache expensive operations** — store external API responses to avoid rate limits or reduce network calls
- **Aggregate historical data** — keep rolling totals or logs that don't belong in Home Assistant state

For real-time Home Assistant entity state, use [`self.states`](../states/index.md) instead. The cache is for *your* app data, not HA state.

## Basic Usage

The cache behaves like a Python dictionary. You can get, set, check membership, and delete keys:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_basic_usage.py"
```

The cache persists to disk automatically. You do not need to open, flush, or close it — Hassette handles that during startup and shutdown.

## How It Works

### Storage Location

Each app or service gets its own cache directory under your configured `data_dir`:

```
{data_dir}/{ClassName}/cache/
```

For example, if your app class is `WeatherApp` and `data_dir` is `/home/user/.hassette`, the cache lives at:

```
/home/user/.hassette/WeatherApp/cache/
```

### Shared Cache

All instances of the same resource class share the same cache directory. If you run `MyApp` as two separate instances with different configurations, both instances read from and write to the same cache.

!!! warning "Use instance name as a key prefix for multi-instance apps"
    If the same app class runs as multiple instances, prefix your keys with `self.app_config.instance_name` to avoid collisions:

    ```python
    --8<-- "pages/core-concepts/cache/snippets/cache_instance_prefix.py"
    ```

### Lazy Initialization

The cache directory is created on first access. If your app never uses `self.cache`, no directory is created.

### Automatic Cleanup

Hassette closes and flushes the cache to disk during app shutdown. You do not need to call any cleanup method.

## Configuration

Control the maximum cache size in `hassette.toml`:

```toml
[hassette]
default_cache_size = 104857600  # 100 MiB (default)
data_dir = "/path/to/data"
```

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `default_cache_size` | integer (bytes) | `104857600` | Maximum size for each resource's cache. When the limit is reached, the least recently used items are evicted. |
| `data_dir` | path | platform-dependent | Root directory for all persistent data. See [Global Settings](../configuration/global.md) for platform defaults. |

## Lifecycle

The cache is managed automatically through the resource lifecycle:

1. **First access** — cache directory is created and the cache is opened
2. **Runtime** — reads and writes happen transparently; the cache is thread-safe
3. **Shutdown** — the cache is closed and all pending writes are flushed to disk

You never need to manually open or close the cache.

## Data Types

The cache stores any Python object that supports [pickling](https://docs.python.org/3/library/pickle.html):

- Primitives: `str`, `int`, `float`, `bool`, `None`
- Collections: `list`, `dict`, `tuple`, `set`
- Timestamps: `ZonedDateTime`, `PlainDateTime`, `Instant`, `TimeDelta` from the `whenever` library
- Hassette models: state instances, event instances
- Custom dataclasses and classes (if they are picklable)

!!! tip "Storing timestamps"
    Use `self.now()` to get the current time as a `ZonedDateTime`. This is the recommended type for timestamps stored in the cache — it is timezone-aware, picklable, and supports arithmetic like `self.now().subtract(hours=4)`.

## See Also

- [Patterns & Examples](patterns.md) — rate-limiting, counters, complex data, expiring entries, best practices, and troubleshooting
- [Global Settings](../configuration/global.md) — `data_dir` and `default_cache_size` reference
- [States](../states/index.md) — real-time HA entity state (not the same as the cache)
- [diskcache documentation](https://grantjenks.com/docs/diskcache/) — the underlying library
