# App Cache: Patterns & Examples

Practical patterns for `self.cache`, the persistent disk-backed key-value store available on every `App` instance. Each pattern addresses a specific problem with a complete, runnable example. The [Overview](index.md) covers setup and basic usage.

`self.now()` returns the current time as a [`ZonedDateTime`](https://whenever.readthedocs.io/) from the `whenever` library. It is timezone-aware, picklable, and supports arithmetic — all time-based patterns below use it for timestamp comparisons.

## Rate-Limiting Notifications

A leak or alarm sensor can fire repeatedly during a single incident. Storing a timestamp in the cache prevents duplicate notifications from going out during a cooldown window:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_rate_limit.py"
```

`P` is `hassette.predicates` — helper functions that filter which events trigger a handler (see [Predicates](../bus/filtering.md)). `P.StateTo("on")` fires the handler only when the entity transitions to `"on"`.

`self.cache.get(cache_key)` returns `None` on the first call, so the notification goes out immediately. The timestamp is written after sending. On subsequent triggers, the handler compares the stored timestamp against the cooldown threshold — `last_sent > self.now().subtract(hours=4)` is true when the last notification was sent less than 4 hours ago. For per-entity rate limiting, include the entity ID in the key: `f"last_notification:{entity_id}"`.

## Persistent Counters

A counter stored only in an instance variable resets to zero whenever Hassette restarts. Loading from the cache at initialization and writing back on every increment makes the counter survive restarts:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_counter.py"
```

`self.cache.get("motion_count", 0)` returns the stored value or `0` when no entry exists. Each call to `on_motion` increments the in-memory counter and immediately writes the new value to disk. Restart Hassette and check the logs — `"Motion count restored: N"` confirms the counter survived.

## API Response Caching

External APIs impose rate limits. Storing the response alongside a timestamp lets the app return a cached copy while the data is still fresh:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_api_response.py"
```

`get_weather` checks the cache first. The entry holds a tuple of `(timestamp, data)`. When the stored timestamp falls within the 30-minute window, the cached value is returned without a network call. A stale or absent entry triggers a fresh fetch and overwrites the cache entry.

## Expiring Entries

Two approaches exist for expiring cache entries, depending on whether access to the timestamp is needed.

For automatic expiry, `self.cache.set()` accepts an `expire` parameter in seconds. The underlying diskcache library removes the entry silently once the timeout elapses:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_expire.py:expire"
```

When the timestamp is needed for display or custom staleness logic, storing it explicitly alongside the value works better:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_expiring.py"
```

`get_cached_data` compares the stored timestamp against the configured TTL and returns `None` when the entry is stale. The caller decides whether to re-fetch.

## Storing Complex Data

The cache stores any picklable Python object. Dataclasses with typed fields work well for structured app state:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_complex_data.py"
```

`dataclasses.replace()` produces a new `EnergyStats` object rather than modifying the existing one. The cache write only happens after the new object is fully constructed. A runtime error before the write leaves the previous value intact.

## Load Once, Write on Shutdown

Cache access involves disk I/O. For values read many times per second, loading into an instance variable at initialization avoids repeated disk reads:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_performance.py"
```

`on_initialize` reads from disk once. All access during the run uses the in-memory copy. `on_shutdown` writes the final state back to disk. The cache is thread-safe, so concurrent handlers can write to it directly when the load-once pattern is not needed. Within a single async event loop, if two handlers update the same key concurrently, the last write wins — for counters or accumulators, use instance variables as shown in the [Persistent Counters](#persistent-counters) pattern.

## Troubleshooting

### Cache Not Persisting

If values do not survive a restart, check four common causes:

- **Write targets a local variable instead of `self.cache`.** Verify the assignment uses `self.cache["key"]`, not a local dict.
- **Exception during initialization.** The app may raise before the write executes. Check `hassette log --app <key>` for errors.
- **Cache directory lacks write permissions.** Check `ls -la {data_dir}/{ClassName}/cache/` — the Hassette process must own the directory.
- **Stored value is not picklable.** Unpicklable objects raise `PicklingError` at write time. Enable `log_level = "DEBUG"` in `hassette.toml` to see the error.

### Cache Size Exceeded

When the cache reaches `default_cache_size`, diskcache silently evicts the least recently used entries. A larger `default_cache_size` in [Global Settings](../configuration/index.md) raises the ceiling. TTL expiry removes stale entries proactively, and storing large objects externally while caching only their identifiers reduces pressure.

Set `log_level = "DEBUG"` in `hassette.toml` to enable cache operation logging. The cache directory at `~/.local/share/hassette/v0/{ClassName}/cache/` (where `{ClassName}` matches the app's class name, e.g. `WaterLeakAlertApp`) should contain data files after the first successful write.

## See Also

- [App Cache Overview](index.md). How it works, configuration, lifecycle.
- [Global Settings](../configuration/index.md). `data_dir` and `default_cache_size`.
- [diskcache documentation](https://grantjenks.com/docs/diskcache/). Full cache library reference.
