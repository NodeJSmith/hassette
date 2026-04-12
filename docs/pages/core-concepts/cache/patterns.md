# App Cache: Patterns & Examples

This page covers practical patterns for `self.cache`. If you are new to the cache, start with the [Overview](index.md) first.

## Pattern: API Response Caching

Avoid hitting external API rate limits by storing responses with a timestamp and checking freshness before making a new request:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_api_response.py"
```

The pattern: check if the cached entry exists and is within the TTL window, return it if so, otherwise fetch fresh data and update the cache.

## Pattern: Rate-Limiting Notifications

Prevent notification spam by recording when the last notification was sent and skipping the call if the cooldown has not elapsed:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_rate_limit.py"
```

For per-entity rate-limiting (e.g., one cooldown per sensor rather than a single global cooldown), include the entity ID in the cache key: `f"last_notification:{event.data.entity_id}"`.

## Pattern: Persistent Counters

Track events across restarts by loading the counter from the cache at initialization and writing it back on every increment:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_counter.py"
```

The counter is restored from disk the next time the app starts, so `motion_count` accumulates across Hassette restarts.

## Pattern: Storing Complex Data

The cache stores any picklable Python object — including dataclasses with typed fields:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_complex_data.py"
```

!!! note "Create new objects instead of mutating"
    Use `dataclasses.replace()` to produce a new object rather than modifying the existing one. This keeps your app logic predictable and avoids partially-written state if an error occurs before the cache write.

## Pattern: Expiring Cache Entries

The cache does not have built-in TTL on individual entries. Implement expiration by storing a timestamp alongside the value:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_expiring.py"
```

## Pattern: Load Once, Write on Shutdown

For data that is read frequently during a run but only needs to be persisted at shutdown, load from the cache at initialization into an instance variable and write back at shutdown:

```python
--8<-- "pages/core-concepts/cache/snippets/cache_performance.py"
```

This avoids disk I/O on every access while still persisting the data across restarts.

## Best Practices

### What to Cache

**Good uses:**

- Notification timestamps for rate-limiting
- External API responses that have a meaningful TTL
- Computed values that are expensive to recalculate
- Rolling counters and statistics
- User preferences or app settings

**Avoid caching:**

- Real-time Home Assistant entity state — use [`self.states`](../states/index.md) instead
- Large binary files — consider external storage
- Session-only temporary flags — use instance variables

### Cache vs. StateManager

| Use Case | Tool | Reason |
|----------|------|--------|
| Current sensor values | [`self.states`](../states/index.md) | Real-time HA state |
| Historical data | `self.cache` | Persists across restarts |
| Computed aggregates | `self.cache` | Not part of HA state |
| External API responses | `self.cache` | Reduce external calls |
| Temporary flags (this run only) | Instance variables | No persistence needed |

### Performance

Cache access involves disk I/O and is not instantaneous. For data that is read many times per second within a single run, load into an instance variable at initialization (see the [Load Once, Write on Shutdown](#pattern-load-once-write-on-shutdown) pattern above). The cache is thread-safe and can be accessed from multiple async tasks concurrently.

## Troubleshooting

### Cache Not Persisting

If data is not surviving restarts:

- Confirm you are writing to `self.cache`, not a local variable named `cache`
- Confirm the app completes initialization without raising an exception (a startup error can prevent the shutdown flush)
- Confirm the cache directory has write permissions
- Confirm the value is picklable — unpicklable objects raise a `PicklingError` at write time

### Cache Size Exceeded

When the cache reaches `default_cache_size`, the least recently used items are evicted automatically. If you are losing important data:

- Increase `default_cache_size` in [Global Settings](../configuration/global.md)
- Implement expiration logic to remove stale entries (see [Expiring Cache Entries](#pattern-expiring-cache-entries))
- Consider storing large objects externally and caching only references or identifiers

### Debugging Cache Operations

Enable debug logging to see cache operations in the logs:

```toml
[hassette]
log_level = "DEBUG"
```

Verify the cache directory exists and contains data:

```bash
ls -lah ~/.local/share/hassette/v0/MyApp/cache/
```

## See Also

- [App Cache Overview](index.md) — how it works, configuration, lifecycle
- [Global Settings](../configuration/global.md) — `data_dir` and `default_cache_size`
- [Apps Overview](../apps/index.md) — app lifecycle
- [diskcache documentation](https://grantjenks.com/docs/diskcache/) — full cache library reference
